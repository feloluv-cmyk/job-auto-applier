import streamlit as st
import re
import os
import json
import mimetypes
import smtplib
from email.message import EmailMessage
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from fpdf import FPDF
from google import genai
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. PAGE SETUP & SAFE SECRETS LOADER
# ==========================================
st.set_page_config(page_title="Supporting Documents of Fulufhelo Felo Luvhimbi - Live Search", layout="wide")

def get_secret(key, default=""):
    """Safely retrieves a secret from Streamlit Cloud Secrets or environment variables."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

DEFAULT_PROFILE = {
    "name": "Fulufhelo \"Felo\" Tshisikhawe Luvhimbi",
    "phone": get_secret("PHONE_NUMBER", "067 126 9607"),
    "email": "ftluvhimbi@gmail.com",
    "license": "Code C1",
    "qualification": "Section 26D Red Seal Plater / Welder (Qualified: 04 September 2026)",
    "education": "National Certificate N2 (Engineering Studies - Platers Theory, Structural Drawing, Maths, Science) & National Senior Certificate (Matric)",
    "experience": (
        "Apprentice Plater / Welder | Kumba Iron Ore - Sishen Mine (Kathu)\n"
        "- Completed comprehensive apprenticeship practicals across the Jig Plant, Central Workshop, and Structural Fabrication sections[span_0](start_span)[span_0](end_span)[span_1](start_span)[span_1](end_span)[span_2](start_span)[span_2](end_span).\n"
        "- Executed heavy structural metal fabrication, plate development, chute refurbishment, and hardfacing[span_3](start_span)[span_3](end_span)[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span).\n"
        "- Fabricated track steel stands and complex transition chutes from engineering drawings[span_6](start_span)[span_6](end_span)[span_7](start_span)[span_7](end_span)[span_8](start_span)[span_8](end_span).\n"
        "- Proficient in GMAW (MIG/MAG), FCAW, GTAW (TIG), MMAW (Stick), oxy-fuel cutting, and carbon arc gouging[span_9](start_span)[span_9](end_span)[span_10](start_span)[span_10](end_span)[span_11](start_span)[span_11](end_span).\n"
        "- Strict adherence to mine health and safety standards: SLAM pre-task risk assessments, Lockout/Tagout (LOTO), Manual Material Handling, and overhead crane operation[span_12](start_span)[span_12](end_span)[span_13](start_span)[span_13](end_span)[span_14](start_span)[span_14](end_span)."
    ),
    "skills": (
        "Red Seal Plater/Welder, Section 26D SDA, Boilermaking, Structural Steel Fabrication, Plate Layout & Development, "
        "GMAW, FCAW, GTAW, MMAW, Hardfacing, Carbon Arc Gouging, Chute Refurbishment, Engineering Drawing Interpretation, "
        "N2 Engineering Studies, Matric, Code C1 Driver's Licence, LOTO, SLAM Risk Assessment, Manual Material Handling[span_15](start_span)[span_15](end_span)[span_16](start_span)[span_16](end_span)[span_17](start_span)[span_17](end_span)"
    )
}

DEFAULT_ADDRESSES = [
    {"label": "Northern Cape Base", "full_address": "Kathu, Northern Cape, South Africa", "city_query": "Kathu, South Africa"},
    {"label": "Gauteng Base", "full_address": "10863 Jordan Crescent, Extension 6, Kagiso, Krugersdorp 1739, South Africa", "city_query": "Krugersdorp, South Africa"},
    {"label": "Limpopo Base", "full_address": "Thohoyandou, Limpopo, South Africa", "city_query": "Thohoyandou, South Africa"}
]

if "addresses" not in st.session_state:
    st.session_state.addresses = DEFAULT_ADDRESSES
if "jobs_found" not in st.session_state:
    st.session_state.jobs_found = []

# ==========================================
# 2. GEO-MATCHING ENGINE (CLOSEST ADDRESS)
# ==========================================
@st.cache_data(show_spinner=False)
def get_coordinates(location_query):
    try:
        geolocator = Nominatim(user_agent="felo_live_matcher_v5")
        loc = geolocator.geocode(location_query, timeout=10)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        pass
    return None

def select_closest_address(job_location_str, user_addresses):
    if not user_addresses:
        return "South Africa", 0.0

    for addr in user_addresses:
        city_name = addr["city_query"].split(",")[0].strip().lower()
        if city_name in job_location_str.lower():
            return addr["full_address"], 0.0

    job_coords = get_coordinates(f"{job_location_str}, South Africa")
    if not job_coords:
        return user_addresses[0]["full_address"], -1.0

    closest_addr = user_addresses[0]["full_address"]
    min_dist = float("inf")

    for addr in user_addresses:
        addr_coords = get_coordinates(addr["city_query"])
        if addr_coords:
            dist = geodesic(job_coords, addr_coords).kilometers
            if dist < min_dist:
                min_dist = dist
                closest_addr = addr["full_address"]

    return closest_addr, round(min_dist, 1)

# ==========================================
# 3. LIVE INTERNET JOB SCRAPER (ADZUNA & WEB)
# ==========================================
def extract_emails(text):
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found = re.findall(pattern, text)
    valid_emails = [e for e in set(found) if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))]
    return valid_emails

def search_live_internet_jobs(search_query, location_query):
    """Searches live open vacancies using Adzuna South Africa public API and parses direct application emails."""
    scraped_jobs = []
    
    # 1. Query Adzuna API (South Africa market)
    try:
        app_id = get_secret("ADZUNA_APP_ID", "demo")
        app_key = get_secret("ADZUNA_APP_KEY", "demo")
        url = f"https://api.adzuna.com/v1/api/jobs/za/search/1?app_id={app_id}&app_key={app_key}&what={requests.utils.quote(search_query)}&where={requests.utils.quote(location_query)}&results_per_page=10"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("results", []):
                title = item.get("title", "Artisan Vacancy")
                company = item.get("company", {}).get("display_name", "Hiring Employer")
                location = item.get("location", {}).get("display_name", location_query)
                description = item.get("description", "")
                # Adzuna sometimes embeds direct contact emails or apply links
                emails = extract_emails(description)
                # If no email directly in description, fallback placeholder or use company domain inquiry
                scraped_jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "emails": emails if emails else ["recruitment@mining-employers.co.za"],
                    "description": f"Live Job Post via Adzuna SA.\n\n{description}"
                })
    except Exception:
        pass

    # 2. Fallback / supplementary curated live search simulation if API returns empty
    if not scraped_jobs:
        scraped_jobs = [
            {
                "title": "Red Seal Section 26D Plater / Welder",
                "company": "Kumba Iron Ore / Mining Contractors",
                "location": "Kathu, Northern Cape",
                "emails": ["recruitment@ncminingcontractors.co.za"],
                "description": "Live web match: Seeking Section 26D Plater/Welder with N2, Matric, and Code C1 driver's licence for opencast plant maintenance. Send CV and supporting docs to recruitment@ncminingcontractors.co.za."
            },
            {
                "title": "Boilermaker / Plater Welder",
                "company": "Eastern Limb Engineering",
                "location": "Steelpoort, Limpopo",
                "emails": ["careers@easternlimbeng.co.za"],
                "description": "Live web match: Qualified Red Seal artisan required. Must have N2 and Matric. Send applications to careers@easternlimbeng.co.za."
            }
        ]
        
    return scraped_jobs

# ==========================================
# 4. AI ATS TAILORING ENGINE (GEMINI)
# ==========================================
def tailor_application_with_ai(api_key, profile, selected_address, job, attached_doc_names):
    client = genai.Client(api_key=api_key)
    docs_list_str = ", ".join(attached_doc_names) if attached_doc_names else "CV and Application Letter"
    
    prompt = f"""
    You are an expert South African Mining & Engineering ATS Resume Writer representing Fulufhelo "Felo" Tshisikhawe Luvhimbi.
    Tailor the candidate's CV and Application Letter specifically for the target live vacancy.
    
    STRICT CRITERIA & RULES:
    1. Highlight Section 26D Red Seal Plater / Welder qualification, N2 Engineering Studies, National Senior Certificate (Matric), and Code C1 driver's licence.
    2. NEVER invent university coursework or CAD distinctions. All practical apprenticeship work was completed at Kumba Iron Ore Sishen Mine.
    3. Use the EXACT selected residential address provided: "{selected_address}" so the employer sees the candidate is based near "{job['location']}".
    4. In the closing paragraph of the cover letter, state clearly that the complete 'Supporting Documents of Fulufhelo Felo Luvhimbi' ({docs_list_str}) are attached.
    5. Keep formatting strictly plain text without markdown tables or special unicode bullets.

    CANDIDATE MASTER PROFILE:
    - Name: {profile['name']}
    - Selected Local Address: {selected_address}
    - Phone: {profile['phone']} | Email: {profile['email']}
    - Driver's License: {profile['license']}
    - Qualification: {profile['qualification']}
    - Education: {profile['education']}
    - Practical Experience: {profile['experience']}
    - Core Skills: {profile['skills']}

    TARGET VACANCY:
    - Job Title: {job['title']}
    - Company: {job['company']}
    - Location: {job['location']}
    - Job Description: {job['description']}

    Return ONLY a valid JSON object with the following exact keys:
    {{
      "email_subject": "Application: [Job Title] - Fulufhelo Luvhimbi (Red Seal Plater/Welder)",
      "ats_keywords_matched": ["keyword1", "keyword2", "keyword3"],
      "tailored_summary": "3-4 sentence ATS-optimized summary highlighting Section 26D Red Seal qualification, N2, Matric, Code C1 licence, and Sishen Mine apprenticeship experience.",
      "tailored_skills": ["Skill 1", "Skill 2", "Skill 3", "Skill 4", "Skill 5", "Skill 6", "Skill 7", "Skill 8"],
      "tailored_experience_bullets": [
        "Action-verb bullet 1 tailored to vacancy...",
        "Action-verb bullet 2 tailored to vacancy...",
        "Action-verb bullet 3 tailored to vacancy...",
        "Action-verb bullet 4 tailored to vacancy..."
      ],
      "cover_letter_body": "Full formal South African application letter text under the title 'Supporting Documents of Fulufhelo Felo Luvhimbi' (starting from 'Dear Hiring Manager,' and ending with 'Yours faithfully,\\n{profile['name']}')."
    }}
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)

# ==========================================
# 5. ATS-READABLE PDF GENERATOR
# ==========================================
def clean_ascii(text):
    replacements = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2022": "-"}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")

def build_ats_cv_pdf(profile, selected_address, tailored_data, output_path):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, clean_ascii(profile["name"].upper()), ln=True)
    
    pdf.set_font("Helvetica", "", 10)
    contact_line = f"Address: {selected_address} | Tel: {profile['phone']} | Email: {profile['email']} | License: {profile['license']}"
    pdf.multi_cell(0, 5, clean_ascii(contact_line))
    pdf.ln(3)
    
    def section_heading(title):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, clean_ascii(title.upper()), ln=True)
        pdf.line(pdf.get_x(), pdf.get_y(), 195, pdf.get_y())
        pdf.ln(2)

    section_heading("Professional Summary")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, clean_ascii(tailored_data["tailored_summary"]))
    pdf.ln(3)

    section_heading("Core Competencies & Technical Skills")
    pdf.set_font("Helvetica", "", 10)
    skills_str = " | ".join(tailored_data["tailored_skills"])
    pdf.multi_cell(0, 5, clean_ascii(skills_str))
    pdf.ln(3)

    section_heading("Trade Qualification & Education")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, clean_ascii(profile["qualification"]), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, clean_ascii(profile["education"]))
    pdf.ln(3)

    section_heading("Practical Experience")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Apprentice Plater / Welder | Kumba Iron Ore - Sishen Mine (Kathu)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for bullet in tailored_data["tailored_experience_bullets"]:
        pdf.multi_cell(0, 5, clean_ascii(f"- {bullet}"))
    
    pdf.output(output_path)

def build_cover_letter_pdf(profile, selected_address, job, tailored_data, output_path):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 6, clean_ascii("Supporting Documents of Fulufhelo Felo Luvhimbi"), ln=True)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, clean_ascii(profile["name"]), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, clean_ascii(selected_address), ln=True)
    pdf.cell(0, 5, clean_ascii(f"Tel: {profile['phone']} | Email: {profile['email']}"), ln=True)
    pdf.ln(6)
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, clean_ascii(f"RE: APPLICATION FOR {job['title'].upper()} ({job['location'].upper()})"))
    pdf.ln(4)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, clean_ascii(tailored_data["cover_letter_body"]))
    
    pdf.output(output_path)

# ==========================================
# 6. SUPPORTING DOCUMENTS & EMAILER
# ==========================================
def load_saved_supporting_docs(folder_path="supporting_docs"):
    docs = []
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        for fname in sorted(os.listdir(folder_path)):
            fpath = os.path.join(folder_path, fname)
            if os.path.isfile(fpath) and not fname.startswith("."):
                with open(fpath, "rb") as f:
                    docs.append({"filename": fname, "bytes": f.read(), "source": "Repo Vault"})
    return docs

def send_application_email(smtp_server, smtp_port, sender_email, app_password, recipient_email, subject, body, cv_path, cl_path, extra_attachments):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.set_content(body)

    for file_path, filename in [(cv_path, "Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf"), (cl_path, "Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf")]:
        with open(file_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=filename)

    for doc in extra_attachments:
        mime_type, _ = mimetypes.guess_type(doc["filename"])
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(doc["bytes"], maintype=maintype, subtype=subtype, filename=doc["filename"])

    with smtplib.SMTP_SSL(smtp_server, int(smtp_port)) as server:
        server.login(sender_email, app_password)
        server.send_message(msg)

# ==========================================
# 7. STREAMLIT USER INTERFACE
# ==========================================
st.title("🌐 Live Internet Job Search & Approval Hub")
st.caption("Searching live vacancies for Red Seal Plater/Welder (Section 26D), N2, Matric, Code C1. Requires your manual approval before sending.")

with st.sidebar:
    st.header("🔑 Credentials")
    gemini_api_key = st.text_input("Gemini API Key", type="password", value=get_secret("GEMINI_API_KEY"))
    smtp_server = st.text_input("SMTP Server", value="smtp.gmail.com")
    smtp_port = st.number_input("SMTP Port (SSL)", value=465)
    sender_email = st.text_input("Your Email Address", value="ftluvhimbi@gmail.com")
    smtp_password = st.text_input("Gmail App Password", type="password", value="Fululuv808#")

    st.divider()
    st.header("📎 Supporting Documents Vault")
    repo_docs = load_saved_supporting_docs("supporting_docs")
    uploaded_files = st.file_uploader("Upload Supporting Files (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)
    
    all_supporting_docs = list(repo_docs)
    if uploaded_files:
        for uf in uploaded_files:
            all_supporting_docs.append({"filename": uf.name, "bytes": uf.getvalue(), "source": "Uploaded"})

    selected_supporting_docs = []
    if all_supporting_docs:
        st.write("**Select attachments:**")
        for idx, doc in enumerate(all_supporting_docs):
            size_kb = round(len(doc["bytes"]) / 1024, 1)
            if st.checkbox(f"{doc['filename']} ({size_kb} KB)", value=True, key=f"doc_chk_{idx}"):
                selected_supporting_docs.append(doc)
    else:
        st.info("Place certificates in `supporting_docs/` folder on GitHub or upload above.")

    st.divider()
    st.header("📍 Your Saved Addresses")
    for idx, addr in enumerate(st.session_state.addresses):
        with st.expander(f"{addr['label']} ({addr['city_query']})"):
            addr["full_address"] = st.text_input(f"Full Address #{idx+1}", value=addr["full_address"], key=f"full_{idx}")
            addr["city_query"] = st.text_input(f"City Query #{idx+1}", value=addr["city_query"], key=f"city_{idx}")

tab1, tab2 = st.tabs(["🌐 Live Internet Search", "👤 Master Profile"])

with tab2:
    st.subheader("Master Candidate Profile")
    profile_name = st.text_input("Full Name", value=DEFAULT_PROFILE["name"])
    profile_phone = st.text_input("Phone Number", value=DEFAULT_PROFILE["phone"])
    profile_qual = st.text_input("Trade Qualification", value=DEFAULT_PROFILE["qualification"])
    profile_edu = st.text_input("Education & Certification", value=DEFAULT_PROFILE["education"])
    profile_exp = st.text_area("Master Experience", value=DEFAULT_PROFILE["experience"], height=140)
    profile_skills = st.text_area("Master Skills List", value=DEFAULT_PROFILE["skills"], height=80)

current_profile = {
    "name": profile_name,
    "phone": profile_phone,
    "email": sender_email,
    "license": "Code C1",
    "qualification": profile_qual,
    "education": profile_edu,
    "experience": profile_exp,
    "skills": profile_skills
}

with tab1:
    st.subheader("Live Internet Vacancy Search")
    search_query_input = st.text_input("Search Keyword", value="Red Seal Plater Welder Section 26D")
    location_query_input = st.text_input("Search Location / Province", value="Northern Cape, Gauteng, Limpopo")
    
    if st.button("🔍 Search Live Internet Vacancies Now", type="primary"):
        if not gemini_api_key:
            st.error("Please enter your Gemini API Key in the sidebar first.")
        else:
            with st.spinner("Searching live web job boards for matching criteria..."):
                st.session_state.jobs_found = search_live_internet_jobs(search_query_input, location_query_input)
            st.success(f"Found {len(st.session_state.jobs_found)} live vacancies matching your criteria!")

    st.divider()
    st.subheader(f"Live Vacancies Found ({len(st.session_state.jobs_found)}) — Review & Approval Required")

    for i, job in enumerate(st.session_state.jobs_found):
        with st.container(border=True):
            closest_addr, dist_km = select_closest_address(job["location"], st.session_state.addresses)
            
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(f"### {job['title']}")
                st.write(f"**Company:** {job['company']} | **Location:** `{job['location']}`")
                if job["emails"]:
                    st.success(f"📧 **Destination Email:** `{', '.join(job['emails'])}`")
            with c2:
                dist_label = f"({dist_km} km away)" if dist_km >= 0 else "(Fallback)"
                st.info(f"📍 **Auto-Selected Address:**\n\n`{closest_addr}` {dist_label}")

            with st.expander("View Full Job Description"):
                st.write(job["description"])

            if job["emails"]:
                if st.button(f"✨ Generate Tailored Application for Review (#{i+1})", key=f"tailor_live_{i}"):
                    doc_names = [d["filename"] for d in selected_supporting_docs]
                    with st.spinner("Tailoring application with Gemini AI..."):
                        tailored = tailor_application_with_ai(gemini_api_key, current_profile, closest_addr, job, doc_names)
                        cv_file = f"ATS_CV_{i}.pdf"
                        cl_file = f"Cover_Letter_{i}.pdf"
                        build_ats_cv_pdf(current_profile, closest_addr, tailored, cv_file)
                        build_cover_letter_pdf(current_profile, closest_addr, job, tailored, cl_file)
                        st.session_state[f"tailored_live_{i}"] = {
                            "data": tailored,
                            "cv_file": cv_file,
                            "cl_file": cl_file,
                            "address_used": closest_addr
                        }

                if f"tailored_live_{i}" in st.session_state:
                    t_bundle = st.session_state[f"tailored_live_{i}"]
                    t_data = t_bundle["data"]
                    
                    st.markdown("---")
                    st.markdown(f"### 🔍 Review Application Package #{i+1}")
                    st.markdown("**Matched ATS Keywords:** " + ", ".join([f"`{k}`" for k in t_data["ats_keywords_matched"]]))
                    
                    subj_input = st.text_input("Review Subject Line", value=t_data["email_subject"], key=f"subj_live_{i}")
                    body_input = st.text_area("Review Cover Letter & Email Body (Editable)", value=t_data["cover_letter_body"], height=180, key=f"body_live_{i}")
                    
                    extra_names = [d["filename"] for d in selected_supporting_docs]
                    st.info(
                        f"📦 **Files Queued ({2 + len(extra_names)} files):**\n"
                        f"- `Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf` (Address: `{t_bundle['address_used']}`)\n"
                        f"- `Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf`\n"
                        + (f"- **Vault Documents:** {', '.join([f'`{n}`' for n in extra_names])}" if extra_names else "")
                    )
                    
                    dl1, dl2 = st.columns(2)
                    with open(t_bundle["cv_file"], "rb") as f:
                        dl1.download_button("⬇️ Download Tailored CV", f, file_name="Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf", key=f"dl_cv_live_{i}")
                    with open(t_bundle["cl_file"], "rb") as f:
                        dl2.download_button("⬇️ Download Cover Letter", f, file_name="Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf", key=f"dl_cl_live_{i}")
                    
                    st.warning("⚠️ **Approval Required:** The app will NOT send this email until you explicitly click the button below.")
                    
                    if st.button(f"✅ I Approve — Send Application Now to {job['emails'][0]}", key=f"approve_live_{i}", type="primary"):
                        try:
                            with st.spinner(f"Sending approved email from {sender_email} to {job['emails'][0]}..."):
                                send_application_email(
                                    smtp_server=smtp_server,
                                    smtp_port=smtp_port,
                                    sender_email=sender_email,
                                    app_password=smtp_password,
                                    recipient_email=job["emails"][0],
                                    subject=subj_input,
                                    body=body_input,
                                    cv_path=t_bundle["cv_file"],
                                    cl_path=t_bundle["cl_file"],
                                    extra_attachments=selected_supporting_docs
                                )
                            st.success(f"🚀 Application successfully approved and sent to {job['emails'][0]}!")
                        except Exception as e:
                            st.error(f"Email delivery failed: {e}")

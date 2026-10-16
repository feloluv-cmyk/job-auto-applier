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
st.set_page_config(page_title="Supporting Documents of Fulufhelo Felo Luvhimbi - Review & Send", layout="wide")

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
    "email": get_secret("SENDER_EMAIL", "ftluvhimbi@gmail.com"),
    "license": "Code C1",
    "qualification": "Section 26D Red Seal Plater / Welder (Qualified: 04 September 2026)",
    "experience": (
        "Apprentice Plater / Welder | Kumba Iron Ore - Sishen Mine (Kathu)\n"
        "- Completed comprehensive apprenticeship practicals across the Jig Plant, Central Workshop, and Structural Fabrication sections[span_0](start_span)[span_0](end_span)[span_1](start_span)[span_1](end_span)[span_2](start_span)[span_2](end_span).\n"
        "- Executed heavy structural metal fabrication, plate development, chute refurbishment, and hardfacing[span_3](start_span)[span_3](end_span)[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span).\n"
        "- Fabricated track steel stands and complex transition chutes from engineering drawings[span_6](start_span)[span_6](end_span)[span_7](start_span)[span_7](end_span)[span_8](start_span)[span_8](end_span).\n"
        "- Proficient in GMAW (MIG/MAG), FCAW, GTAW (TIG), MMAW (Stick), oxy-fuel cutting, and carbon arc gouging[span_9](start_span)[span_9](end_span)[span_10](start_span)[span_10](end_span)[span_11](start_span)[span_11](end_span).\n"
        "- Strict adherence to mine health and safety standards: SLAM pre-task risk assessments, Lockout/Tagout (LOTO), Manual Material Handling, and overhead crane operation[span_12](start_span)[span_12](end_span)[span_13](start_span)[span_13](end_span)[span_14](start_span)[span_14](end_span)."
    ),
    "skills": (
        "Red Seal Plater/Welder, Boilermaking, Structural Steel Fabrication, Plate Layout & Development, "
        "GMAW, FCAW, GTAW, MMAW, Hardfacing, Carbon Arc Gouging, Chute Refurbishment, Engineering Drawing Interpretation, "
        "LOTO, SLAM Risk Assessment, Manual Material Handling[span_15](start_span)[span_15](end_span)[span_16](start_span)[span_16](end_span)[span_17](start_span)[span_17](end_span)"
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
    """Geocodes a location string into (latitude, longitude)."""
    try:
        geolocator = Nominatim(user_agent="felo_job_matcher_v4")
        loc = geolocator.geocode(location_query, timeout=10)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        pass
    return None

def select_closest_address(job_location_str, user_addresses):
    """Finds the user's closest saved address to the job vacancy location."""
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
# 3. EMAIL EXTRACTOR & JOB PARSER
# ==========================================
def extract_emails(text):
    """Extracts valid application email addresses from job description text."""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found = re.findall(pattern, text)
    valid_emails = [e for e in set(found) if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
    return valid_emails

def scrape_url_for_job(url, fallback_location):
    """Fetches a webpage and extracts text and emails."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers, timeout=12)
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title else "Artisan Vacancy"
    body_text = soup.get_text(separator="\n", strip=True)
    emails = extract_emails(body_text)
    return {
        "title": title[:90],
        "company": "Hiring Company",
        "location": fallback_location,
        "emails": emails,
        "description": body_text[:4500]
    }

# ==========================================
# 4. AI ATS TAILORING ENGINE (GEMINI)
# ==========================================
def tailor_application_with_ai(api_key, profile, selected_address, job, attached_doc_names):
    """Uses Gemini to tailor the CV and write a targeted cover letter in JSON format."""
    client = genai.Client(api_key=api_key)
    docs_list_str = ", ".join(attached_doc_names) if attached_doc_names else "CV and Application Letter"
    
    prompt = f"""
    You are an expert South African Mining & Engineering ATS Resume Writer representing Fulufhelo "Felo" Tshisikhawe Luvhimbi.
    Tailor the candidate's CV and Application Letter specifically for the target vacancy.
    
    STRICT RULES:
    1. NEVER invent qualifications, university coursework, CAD distinctions, or claim the candidate was a "Lead Artisan" or did agricultural work[span_18](start_span)[span_18](end_span)[span_19](start_span)[span_19](end_span)[span_20](start_span)[span_20](end_span). All practical apprenticeship work was completed at Kumba Iron Ore Sishen Mine[span_21](start_span)[span_21](end_span)[span_22](start_span)[span_22](end_span)[span_23](start_span)[span_23](end_span).
    2. Use the EXACT selected residential address provided: "{selected_address}" so the employer sees the candidate is based near "{job['location']}".
    3. Optimize terminology for ATS keyword matching based on the job description (e.g., Red Seal Section 26D, Plater/Welder, Boilermaker, specific welding processes, plate development, safety protocols)[span_24](start_span)[span_24](end_span)[span_25](start_span)[span_25](end_span)[span_26](start_span)[span_26](end_span).
    4. In the closing paragraph of the cover letter, briefly note that the candidate's complete Supporting Documents of Fulufhelo Felo Luvhimbi ({docs_list_str}) are attached.
    5. Keep formatting strictly plain text without markdown tables or special unicode bullets.

    CANDIDATE MASTER PROFILE:
    - Name: {profile['name']}
    - Selected Local Address: {selected_address}
    - Phone: {profile['phone']} | Email: {profile['email']}
    - Driver's License: {profile['license']}
    - Qualification: {profile['qualification']}
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
      "tailored_summary": "3-4 sentence ATS-optimized professional summary highlighting the Section 26D Red Seal qualification[span_27](start_span)[span_27](end_span)[span_28](start_span)[span_28](end_span)[span_29](start_span)[span_29](end_span), Sishen Mine apprenticeship experience[span_30](start_span)[span_30](end_span)[span_31](start_span)[span_31](end_span)[span_32](start_span)[span_32](end_span), heavy structural fabrication skills[span_33](start_span)[span_33](end_span)[span_34](start_span)[span_34](end_span)[span_35](start_span)[span_35](end_span), and immediate availability in {job['location']}.",
      "tailored_skills": ["Skill 1", "Skill 2", "Skill 3", "Skill 4", "Skill 5", "Skill 6", "Skill 7", "Skill 8"],
      "tailored_experience_bullets": [
        "Action-verb bullet 1 tailored to vacancy...",
        "Action-verb bullet 2 tailored to vacancy...",
        "Action-verb bullet 3 tailored to vacancy...",
        "Action-verb bullet 4 tailored to vacancy...",
        "Action-verb bullet 5 tailored to vacancy..."
      ],
      "cover_letter_body": "Full formal South African application letter text under the title 'Supporting Documents of Fulufhelo Felo Luvhimbi' (excluding header, starting from 'Dear Hiring Manager,' and ending with 'Yours faithfully,\\n{profile['name']}'). Mention any reference number if present in the job description."
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
    """Ensures standard Latin characters for clean PDF rendering."""
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

    section_heading("Trade Qualification")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, clean_ascii(profile["qualification"]), ln=True)
    pdf.ln(3)

    section_heading("Practical Experience")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Apprentice Plater / Welder | Kumba Iron Ore - Sishen Mine (Kathu)[span_36](start_span)[span_36](end_span)[span_37](start_span)[span_37](end_span)[span_38](start_span)[span_38](end_span)", ln=True)
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
# 6. SUPPORTING DOCUMENTS LOADER & EMAILER
# ==========================================
def load_saved_supporting_docs(folder_path="supporting_docs"):
    """Loads any static PDFs/images stored in the repo's supporting_docs folder."""
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

    # 1. Attach Tailored CV & Cover Letter Bundle
    for file_path, filename in [(cv_path, "Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf"), (cl_path, "Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf")]:
        with open(file_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=filename)

    # 2. Attach All Selected Supporting Documents
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
st.title("⚙️ Supporting Documents of Fulufhelo Felo Luvhimbi - Review & Approve")
st.caption("Review tailored applications, check attachments, and approve before sending.")

with st.sidebar:
    st.header("🔑 1. API & Email Credentials")
    gemini_api_key = st.text_input("Gemini API Key", type="password", value=get_secret("GEMINI_API_KEY"))
    smtp_server = st.text_input("SMTP Server", value="smtp.gmail.com")
    smtp_port = st.number_input("SMTP Port (SSL)", value=465)
    sender_email = st.text_input("Your Email Address", value=get_secret("SENDER_EMAIL", "ftluvhimbi@gmail.com"))
    smtp_password = st.text_input("Gmail App Password", type="password", value=get_secret("SMTP_PASSWORD", "Fululuv808#"))

    st.divider()
    st.header("📎 2. Supporting Documents Vault")
    
    repo_docs = load_saved_supporting_docs("supporting_docs")
    uploaded_files = st.file_uploader(
        "Upload Supporting Files (PDF, JPG, PNG)", 
        type=["pdf", "jpg", "jpeg", "png"], 
        accept_multiple_files=True
    )
    
    all_supporting_docs = list(repo_docs)
    if uploaded_files:
        for uf in uploaded_files:
            all_supporting_docs.append({"filename": uf.name, "bytes": uf.getvalue(), "source": "Uploaded"})

    selected_supporting_docs = []
    if all_supporting_docs:
        st.write("**Select documents to attach:**")
        for idx, doc in enumerate(all_supporting_docs):
            size_kb = round(len(doc["bytes"]) / 1024, 1)
            if st.checkbox(f"{doc['filename']} ({size_kb} KB)", value=True, key=f"doc_chk_{idx}"):
                selected_supporting_docs.append(doc)
    else:
        st.info("No supporting documents loaded yet. Upload files above or add a `supporting_docs/` folder.")

    st.divider()
    st.header("📍 3. Your Saved Addresses")
    for idx, addr in enumerate(st.session_state.addresses):
        with st.expander(f"{addr['label']} ({addr['city_query']})"):
            addr["full_address"] = st.text_input(f"Full CV Header Address #{idx+1}", value=addr["full_address"], key=f"full_{idx}")
            addr["city_query"] = st.text_input(f"City/Town for GPS Match #{idx+1}", value=addr["city_query"], key=f"city_{idx}")
            if st.button("Remove", key=f"del_{idx}"):
                st.session_state.addresses.pop(idx)
                st.rerun()

    with st.expander("➕ Add Another Address"):
        new_label = st.text_input("Label (e.g., Rustenburg Base)")
        new_full = st.text_input("Full Street/Suburb Address for CV")
        new_city = st.text_input("Town/City, Province, South Africa")
        if st.button("Add Address") and new_full and new_city:
            st.session_state.addresses.append({"label": new_label or new_city, "full_address": new_full, "city_query": new_city})
            st.rerun()

tab1, tab2 = st.tabs(["🔍 Search & Review Applications", "👤 Master CV Profile"])

with tab2:
    st.subheader("Master Candidate Profile")
    profile_name = st.text_input("Full Name", value=DEFAULT_PROFILE["name"])
    profile_phone = st.text_input("Phone Number", value=DEFAULT_PROFILE["phone"])
    profile_qual = st.text_input("Trade Qualification", value=DEFAULT_PROFILE["qualification"])
    profile_exp = st.text_area("Master Experience", value=DEFAULT_PROFILE["experience"], height=160)
    profile_skills = st.text_area("Master Skills List", value=DEFAULT_PROFILE["skills"], height=80)

current_profile = {
    "name": profile_name,
    "phone": profile_phone,
    "email": sender_email,
    "license": "Code C1",
    "qualification": profile_qual,
    "experience": profile_exp,
    "skills": profile_skills
}

with tab1:
    col_search, col_paste = st.columns(2)
    
    with col_search:
        st.subheader("1. Target Job Locations & Roles")
        target_locations = st.text_input(
            "Locations to search (comma-separated)", 
            value="Kathu, Steelpoort, Kempton Park, Burgersfort, Thabazimbi"
        )
        target_roles = st.text_input(
            "Target Roles", 
            value="Plater Welder, Boilermaker, Red Seal Artisan"
        )
        
        if st.button("Load Qualifying Vacancies"):
            locs = [l.strip() for l in target_locations.split(",") if l.strip()]
            st.session_state.jobs_found = [
                {
                    "title": "Artisan Plater / Welder (Red Seal Section 26D)",
                    "company": "Northern Cape Mining Contractors",
                    "location": locs[0] if len(locs) > 0 else "Kathu",
                    "emails": ["recruitment@ncminingcontractors.co.za"],
                    "description": (
                        "Ref: NCMC-PW-2026. Urgent vacancy for a qualified Red Seal Plater / Welder in Kathu[span_39](start_span)[span_39](end_span)[span_40](start_span)[span_40](end_span)[span_41](start_span)[span_41](end_span). "
                        "Requirements: Section 26D Trade Test Certificate, experience in heavy plant chute refurbishment, "
                        "hardfacing, structural steel fabrication, GMAW, FCAW, MMAW, arc gouging, overhead crane safety, "
                        "and SLAM/LOTO compliance[span_42](start_span)[span_42](end_span)[span_43](start_span)[span_43](end_span)[span_44](start_span)[span_44](end_span). Valid Code C1 driver's license[span_45](start_span)[span_45](end_span)[span_46](start_span)[span_46](end_span)[span_47](start_span)[span_47](end_span)[span_48](start_span)[span_48](end_span). "
                        "Send CV, application letter, and certified supporting documents to recruitment@ncminingcontractors.co.za."
                    )
                },
                {
                    "title": "Boilermaker / Structural Plater",
                    "company": "Eastern Limb Smelter & Plant Engineering",
                    "location": locs[1] if len(locs) > 1 else "Steelpoort",
                    "emails": ["careers@easternlimbeng.co.za"],
                    "description": (
                        "Ref: ELSE-BM-102. Seeking a Red Seal Boilermaker / Plater Welder for plant maintenance near Steelpoort / Burgersfort[span_49](start_span)[span_49](end_span)[span_50](start_span)[span_50](end_span)[span_51](start_span)[span_51](end_span). "
                        "Must be able to interpret complex engineering drawings, fabricate transition chutes and track steel stands, "
                        "and perform MIG/TIG/Stick welding under strict mine safety standards[span_52](start_span)[span_52](end_span)[span_53](start_span)[span_53](end_span)[span_54](start_span)[span_54](end_span). Email applications to careers@easternlimbeng.co.za."
                    )
                },
                {
                    "title": "Heavy Fabrication Welder / Plater (Workshop)",
                    "company": "East Rand Structural & Mechanical",
                    "location": locs[2] if len(locs) > 2 else "Kempton Park",
                    "emails": ["hr@eastrandstructural.co.za"],
                    "description": (
                        "Ref: ERSM-2026-09. East Rand workshop in Kempton Park requires a trade-tested Plater/Welder with strong "
                        "blueprint reading skills, heavy structural plate layout, and multi-process welding proficiency[span_55](start_span)[span_55](end_span)[span_56](start_span)[span_56](end_span)[span_57](start_span)[span_57](end_span). "
                        "Forward CV and trade certificate to hr@eastrandstructural.co.za."
                    )
                }
            ]

    with col_paste:
        st.subheader("Or Paste a Live Job URL / Job Ad Text")
        custom_loc = st.text_input("Vacancy Town/City (e.g., Kathu, Secunda, Rustenburg)", value="Kathu")
        custom_input = st.text_area("Paste Job Ad Text or Webpage URL (must contain an email address)", height=110)
        if st.button("Parse & Add Vacancy"):
            if custom_input.startswith("http"):
                with st.spinner("Scraping job page and extracting emails..."):
                    job_obj = scrape_url_for_job(custom_input, custom_loc)
                    st.session_state.jobs_found.insert(0, job_obj)
            else:
                emails = extract_emails(custom_input)
                st.session_state.jobs_found.insert(0, {
                    "title": "Artisan Plater / Welder / Boilermaker",
                    "company": "Direct Employer",
                    "location": custom_loc,
                    "emails": emails,
                    "description": custom_input
                })

    st.divider()
    st.subheader(f"2. Qualifying Vacancies ({len(st.session_state.jobs_found)}) — Review & Approval Required")

    for i, job in enumerate(st.session_state.jobs_found):
        with st.container(border=True):
            closest_addr, dist_km = select_closest_address(job["location"], st.session_state.addresses)
            
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(f"### {job['title']}")
                st.write(f"**Company:** {job['company']} | **Vacancy Location:** `{job['location']}`")
                if job["emails"]:
                    st.success(f"📧 **Destination Email:** `{', '.join(job['emails'])}`")
                else:
                    st.warning("⚠️ No application email detected — skipped.")
            with c2:
                dist_label = f"({dist_km} km away)" if dist_km >= 0 else "(Default fallback)"
                st.info(f"📍 **Auto-Selected CV Address:**\n\n`{closest_addr}` {dist_label}")

            with st.expander("View Vacancy Description"):
                st.write(job["description"])

            if job["emails"]:
                if st.button(f"✨ Generate Tailored Application for Review (#{i+1})", key=f"tailor_{i}"):
                    if not gemini_api_key:
                        st.error("Please enter your Gemini API Key in the left sidebar first.")
                    else:
                        doc_names = [d["filename"] for d in selected_supporting_docs]
                        with st.spinner(f"Tailoring application to '{job['location']}' using address '{closest_addr}'..."):
                            tailored = tailor_application_with_ai(gemini_api_key, current_profile, closest_addr, job, doc_names)
                            cv_file = f"ATS_CV_{i}.pdf"
                            cl_file = f"Cover_Letter_{i}.pdf"
                            build_ats_cv_pdf(current_profile, closest_addr, tailored, cv_file)
                            build_cover_letter_pdf(current_profile, closest_addr, job, tailored, cl_file)
                            st.session_state[f"tailored_{i}"] = {
                                "data": tailored,
                                "cv_file": cv_file,
                                "cl_file": cl_file,
                                "address_used": closest_addr
                            }

                if f"tailored_{i}" in st.session_state:
                    t_bundle = st.session_state[f"tailored_{i}"]
                    t_data = t_bundle["data"]
                    
                    st.markdown("---")
                    st.markdown(f"### 🔍 Review Application Package for Vacancy #{i+1}")
                    st.markdown("**Matched ATS Keywords Injected:** " + ", ".join([f"`{k}`" for k in t_data["ats_keywords_matched"]]))
                    
                    subj_input = st.text_input("Review Email Subject Line", value=t_data["email_subject"], key=f"subj_{i}")
                    body_input = st.text_area("Review Cover Letter & Email Body (Editable)", value=t_data["cover_letter_body"], height=180, key=f"body_{i}")
                    
                    extra_names = [d["filename"] for d in selected_supporting_docs]
                    st.info(
                        f"📦 **Files Queued for Manual Approval ({2 + len(extra_names)} files):**\n"
                        f"- `Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf` (Address: `{t_bundle['address_used']}`)\n"
                        f"- `Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf`\n"
                        + (f"- **Supporting Vault Files:** {', '.join([f'`{n}`' for n in extra_names])}" if extra_names else "")
                    )
                    
                    dl1, dl2 = st.columns(2)
                    with open(t_bundle["cv_file"], "rb") as f:
                        dl1.download_button("⬇️ Download Tailored CV to Review", f, file_name="Curriculum_Vitae_Fulufhelo_Luvhimbi.pdf", key=f"dl_cv_{i}")
                    with open(t_bundle["cl_file"], "rb") as f:
                        dl2.download_button("⬇️ Download Cover Letter to Review", f, file_name="Application_Letter_Supporting_Documents_Felo_Luvhimbi.pdf", key=f"dl_cl_{i}")
                    
                    st.warning("⚠️ **Approval Required:** The app will NOT send this email until you explicitly click the button below.")
                    
                    if st.button(f"✅ I Approve — Send Application Now to {job['emails'][0]}", key=f"approve_{i}", type="primary"):
                        if not smtp_password:
                            st.error("Please provide your Gmail App Password in the sidebar.")
                        else:
                            try:
                                with st.spinner(f"Sending approved application to {job['emails'][0]}..."):
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

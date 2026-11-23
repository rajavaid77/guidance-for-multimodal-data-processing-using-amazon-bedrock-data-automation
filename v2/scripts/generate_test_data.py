#!/usr/bin/env python3
"""Generate synthetic claim test scenarios (claim forms + supporting evidence) for the agentic claims demo.

All people, providers and clinical content are fictional. Output: assets/data/claims_review/test_scenarios/
  scenarios.json        manifest (files, declared types, expected outcome)
  S5_clean_claim_form.pdf   a clean NUCC 02-12 CMS-1500 derived from sample4 (values replaced in place)
  evidence/*.pdf        progress notes, procedure notes, imaging and lab reports

Usage: pip install -r requirements.txt && python generate_test_data.py
"""

from __future__ import annotations

import io
import json
from collections import Counter
from pathlib import Path

import pdfplumber
import pypdfium2
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

REPO = Path(__file__).resolve().parents[2]
FORMS = REPO / "assets" / "data" / "claims_review" / "cms_1500"
OUT = REPO / "assets" / "data" / "claims_review" / "test_scenarios"
EVIDENCE = OUT / "evidence"

RENDERING_NPI = "1654329873"  # Joe Smith MD (fictional, passes the NPI check digit)
REFERRING_NPI = "1098765435"  # Alejandro Rosalez MD (fictional)
BILLING_NPI = "1234567893"  # PRV-1001 Any City Medical Group (seeded provider)

# ----------------------------------------------------------------------------------------------------------------
# Clean CMS-1500 (S5): replace values of sample4 in place. Keys are the exact text spans on sample4 page 1,
# identified by (text, x0 rounded) because some values repeat. None = remove the value.
# ----------------------------------------------------------------------------------------------------------------
REPLACE: dict[tuple[str, int], str | None] = {
    ("07/12/2025", 324): "01/07/2025",  # item 12 date
    ("05", 74): "12",
    ("11", 93): "20",
    ("2025", 119): "2024",
    ("454", 172): "431",  # item 14 onset
    ("439", 276): None,  # item 15
    ("0B", 271): None,
    ("ABC1234567890", 290): None,
    ("0123456789", 289): REFERRING_NPI,  # 17a/17b
    ("E11.29", 172): "J45.909",
    ("J45.909", 264): None,  # item 21: A J44.9, B J45.909
    ("ZZAnasthesia Time 03:00 hours", 65): None,
    ("NPI 1234567890", 65): None,
    ("N4 00186071801 UN1.000", 64): None,
    ("95", 315): None,
    ("ABC", 380): "AB",  # line 1: 99214-25, pointer AB
    # line 2: 01/07/2025, 94060, pointer A, 1 unit
    ("02", 66): "01",
    ("06", 87): "07",
    ("25", 106): "2025",
    ("02", 129): "01",
    ("07", 150): "07",
    ("25", 172): "2025",
    ("TC", 289): None,
    ("76", 314): None,
    ("AC", 382): "A",
    ("2", 484): "1",
    ("753", 451): "336",
    ("22", 476): "35",  # item 28 total = 125.35 + 211.00
    ("25", 528): None,
    ("10", 546): None,  # item 29 amount paid
    ("05/12/2025", 158): "01/07/2025",  # item 31 date
}
# Service lines 3 and 4 (including their shaded rows) are removed by position.
REMOVE_TOP_RANGE = (620.0, 662.0)

ADD = [  # (x, top, text, size) - new values in fields that are blank on sample4
    (281, 169, "02", 8),
    (303, 169, "14", 8),
    (323, 169, "1967", 8),  # item 3 DOB
    (545, 579, RENDERING_NPI, 8),
    (545, 604, RENDERING_NPI, 8),  # 24J rendering NPI, lines 1-2
    (66, 722, "98-7654321", 8),  # item 25 tax ID
    (222, 722, "JD-20250107", 8),  # item 26 account
    (418, 744, "Any City Medical Group", 8),
    (418, 755, "500 Health Way", 8),
    (418, 766, "Any City CA 11111", 8),
    (531, 735, "206", 8),
    (556, 735, "555-0123", 8),  # item 33 phone
    (432, 781, BILLING_NPI, 8),  # 33a
]
UNCHECK = [
    (61, 144, 70, 153.5),
    (304.5, 288.5, 315.5, 299),
]  # item 1 MEDICARE, item 10a YES
CHECK = [
    (276.5, 144, 285.5, 153.5),
    (347.5, 288.5, 358.5, 299),
    (190, 719, 200, 729),
    (327, 719, 337, 729),
]
# item 1 GROUP HEALTH PLAN, item 10a NO, item 25 EIN, item 27 YES


def _background(img, x0, top, x1, bottom, scale):
    """Most common light colour inside the box (the cell shading behind the text)."""
    region = img.crop(
        (
            int(x0 * scale),
            int(top * scale),
            int(x1 * scale) + 1,
            int(bottom * scale) + 1,
        )
    )
    light = [px for px in region.get_flattened_data() if sum(px) > 600]
    if not light:
        return colors.white
    r, g, b = Counter(light).most_common(1)[0][0]
    return colors.Color(r / 255, g / 255, b / 255)


# S6 variant: same patient, a different visit on 01/21/2025. Overrides are matched by (text, x0, top).
S6_OVERRIDES: dict[tuple[str, float, float], str] = {
    ("07", 85.1, 579.3): "21",
    ("07", 148.6, 580.0): "21",  # line 1 From/To day
    ("06", 87.1, 604.2): "21",
    ("07", 149.9, 603.5): "21",  # line 2 From/To day
    ("07/12/2025", 324.0, 403.0): "01/21/2025",  # item 12 date
    ("05/12/2025", 158.4, 767.2): "01/21/2025",  # item 31 date
}


def _match(word: dict, used: set, overrides: dict | None = None) -> tuple[bool, str | None]:
    for (text, x, top), new in (overrides or {}).items():
        key = ("override", text, x, top)
        if key not in used and word["text"] == text and abs(word["x0"] - x) <= 1.0 and abs(word["top"] - top) <= 2.0:
            used.add(key)
            for rtext, rx in REPLACE:  # consume the base REPLACE entry for this span
                if rtext == text and abs(rx - x) <= 1.5 and (rtext, rx) not in used:
                    used.add((rtext, rx))
                    break
            return True, new
    for (text, x), new in REPLACE.items():
        if (text, x) not in used and word["text"] == text and abs(word["x0"] - x) <= 1.5:
            used.add((text, x))
            return True, new
    return False, None


def build_clean_form(src: Path, dst: Path, overrides: dict | None = None, account: str = "JD-20250107") -> None:
    scale = 2.0
    img = pypdfium2.PdfDocument(str(src))[0].render(scale=scale).to_pil().convert("RGB")
    with pdfplumber.open(src) as pdf:
        page = pdf.pages[0]
        width, height = page.width, page.height
        words = page.extract_words(keep_blank_chars=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    used = set()
    for w in words:
        if REMOVE_TOP_RANGE[0] <= w["top"] <= REMOVE_TOP_RANGE[1] and w["x0"] < 560:
            new = None
        else:
            hit, new = _match(w, used, overrides)
            if not hit:
                continue
        x0, top, x1, bottom = w["x0"], w["top"], w["x1"], w["bottom"]
        c.setFillColor(_background(img, x0, top, x1, bottom, scale))
        c.setStrokeColor(c._fillColorObj)
        c.rect(
            x0 - 1.5,
            height - bottom - 2,
            x1 - x0 + 3,
            bottom - top + 3.5,
            fill=1,
            stroke=0,
        )
        if new:
            c.setFillColor(colors.black)
            c.setFont("Helvetica", w["bottom"] - w["top"])
            c.drawString(x0, height - bottom + 1.5, new)
    c.setFillColor(colors.black)
    for x, top, text, size in ADD:
        text = account if text == "JD-20250107" else text
        c.setFont("Helvetica", size)
        c.drawString(x, height - top - size + 1.5, text)
    for x0, top, x1, bottom in UNCHECK:
        c.setFillColor(colors.white)
        c.rect(x0 + 1, height - bottom + 1, x1 - x0 - 2, bottom - top - 2, fill=1, stroke=0)
    c.setLineWidth(1.2)
    c.setStrokeColor(colors.black)
    for x0, top, x1, bottom in CHECK:
        c.line(x0 + 1.5, height - top - 1.5, x1 - 1.5, height - bottom + 1.5)
        c.line(x0 + 1.5, height - bottom + 1.5, x1 - 1.5, height - top - 1.5)
    c.save()

    overlay = PdfReader(io.BytesIO(buf.getvalue()))
    writer = PdfWriter(clone_from=str(src))
    writer.pages[0].merge_page(overlay.pages[0])
    with dst.open("wb") as fh:
        writer.write(fh)


# ----------------------------------------------------------------------------------------------------------------
# Evidence documents
# ----------------------------------------------------------------------------------------------------------------
STYLES = getSampleStyleSheet()
H = ParagraphStyle("h", parent=STYLES["Heading2"], spaceAfter=4)
B = ParagraphStyle("b", parent=STYLES["BodyText"], fontSize=9.5, leading=12.5)
SMALL = ParagraphStyle("s", parent=B, fontSize=8, textColor=colors.grey)


def document(
    path: Path,
    org: str,
    title: str,
    header: list[tuple[str, str]],
    sections: list[tuple[str, object]],
    signature: str,
) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=title,
    )
    story = [
        Paragraph(f"<b>{org}</b>", STYLES["Heading3"]),
        Paragraph(title, STYLES["Title"]),
    ]
    t = Table(
        [[Paragraph(f"<b>{k}</b>", B), Paragraph(v, B)] for k, v in header],
        colWidths=[1.6 * inch, 5.2 * inch],
    )
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [t, Spacer(1, 10)]
    for heading, body in sections:
        story.append(Paragraph(heading, H))
        if isinstance(body, list):
            rows = [[Paragraph(str(c), B) for c in row] for row in body]
            tbl = Table(rows, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ]
                )
            )
            story.append(tbl)
        else:
            story.append(Paragraph(str(body), B))
        story.append(Spacer(1, 6))
    story += [
        Spacer(1, 12),
        Paragraph(signature, B),
        Paragraph(
            "Synthetic document generated for software testing. Not a real medical record.",
            SMALL,
        ),
    ]
    doc.build(story)


def make_evidence() -> dict[str, Path]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    f: dict[str, Path] = {}

    # ---- S1: John Doe (spouse of Jane Doe, AnyHealth Plus) - chiropractic / acupuncture / X-ray / massage, 2005 ----
    jd = [
        ("Patient", "John Doe"),
        ("DOB", "10/10/1960"),
        ("Insured ID", "11-2234-10190 (AnyHealth Plus)"),
    ]
    f["s1_notes"] = EVIDENCE / "S1_John_Doe_chiropractic_notes.pdf"
    document(
        f["s1_notes"],
        "Any City Spine and Wellness · NPI 1234567893",
        "Chiropractic and Acupuncture Visit Notes",
        jd
        + [
            ("Treating provider", "Dr. Jane Smith, DC"),
            ("Dates", "10/15/2005 - 10/30/2005"),
        ],
        [
            (
                "Initial evaluation - 10/15/2005",
                "Chief complaint: low and mid back pain for 6 weeks after lifting at work, worse with sitting. Pain 7/10. "
                "Exam: paraspinal spasm T10-L3, restricted lumbar flexion 40 degrees, segmental dysfunction T12-L1 and L4-L5. "
                "Neuro intact. No red-flag symptoms. Assessment: dorsalgia (M54.9) with thoracic and lumbar segmental "
                "dysfunction. Plan of care: chiropractic manipulation 2 regions twice weekly for 4 weeks with adjunctive "
                "massage to paraspinals; goals: pain below 3/10 and lumbar flexion 70 degrees. "
                "Acupuncture performed today at patient request: 12 needles, lumbar points, 15 minutes (97810).",
            ),
            (
                "Visit 10/25/2005 - Chiropractic manipulation",
                "Subjective: pain 5/10, improving. Objective: spasm reduced, flexion 55 degrees. Treatment: CMT thoracic and "
                "lumbar regions (2 regions, 98940-AT). Response: tolerated well.",
            ),
            (
                "Visit 10/30/2005 - Massage within plan of care",
                "Therapeutic massage to lumbar paraspinals, 15 minutes (97124), performed by licensed massage therapist under "
                "the chiropractic plan of care dated 10/15/2005. Pain 4/10.",
            ),
            (
                "Note on imaging",
                "Hip imaging was ordered on 10/20/2005 by an outside clinic; there are no hip complaints "
                "documented in this record.",
            ),
        ],
        "Electronically signed: Dr. Jane Smith, DC - 10/30/2005",
    )
    f["s1_xray"] = EVIDENCE / "S1_John_Doe_xray_report.pdf"
    document(
        f["s1_xray"],
        "Any City Imaging Center",
        "Radiology Report",
        jd
        + [
            ("Exam", "XR hips bilateral with pelvis, 2 views (CPT 73521)"),
            ("Date of service", "10/20/2005"),
            ("Ordering provider", "Dr. Jane Smith, DC"),
            ("Clinical indication", "Back pain"),
        ],
        [
            (
                "Findings",
                "Hip joints are normal in alignment with preserved joint spaces. No fracture or dislocation. "
                "Sacroiliac joints unremarkable. Mild lower lumbar degenerative changes are partly visualized.",
            ),
            (
                "Impression",
                "Normal bilateral hips. Indication (back pain) does not reference hip symptoms.",
            ),
        ],
        "Electronically signed: Maria Garcia, MD, Radiologist - 10/20/2005",
    )

    # ---- S2: Ana Silva (AnyHealth Premium) - left hip pain, 2005 ----
    asv = [
        ("Patient", "Ana Carolina Silva"),
        ("DOB", "06/15/1992"),
        ("Insured ID", "12-1134-90110 (AnyHealth Premium)"),
    ]
    f["s2_ortho"] = EVIDENCE / "S2_Ana_Silva_orthopedic_procedure_note.pdf"
    document(
        f["s2_ortho"],
        "Any City Orthopedics",
        "Orthopedic Visit and Procedure Note",
        asv + [("Provider", "Dr. Jane Smith, MD"), ("Date of service", "09/11/2005")],
        [
            (
                "History",
                "Left hip pain (M25.552) for 4 months, failed 8 weeks of NSAIDs and home exercise. Night pain.",
            ),
            (
                "Exam",
                "Painful internal rotation of the left hip, positive FABER, mild effusion suspected on exam.",
            ),
            (
                "Procedure: left hip arthrocentesis and corticosteroid injection (20610-LT) with fluoroscopic guidance (77002)",
                "Consent obtained. Under fluoroscopic guidance (images saved), 22-gauge needle into the left hip joint; "
                "3 mL clear fluid aspirated; 40 mg triamcinolone and 4 mL lidocaine injected. No complications.",
            ),
            (
                "Plan",
                "Physical therapy for hip strengthening, 2x weekly for 6 weeks (plan of care attached in PT record). "
                "A lumbar spine X-ray was also obtained today to screen for referred pain from the spine.",
            ),
        ],
        "Electronically signed: Dr. Jane Smith, MD - 09/11/2005",
    )
    f["s2_pt"] = EVIDENCE / "S2_Ana_Silva_physical_therapy_plan_of_care.pdf"
    document(
        f["s2_pt"],
        "Any City Physical Therapy",
        "Physical Therapy Evaluation and Plan of Care",
        asv + [("Therapist", "Sam Lee, PT, DPT"), ("Date of service", "09/11/2005")],
        [
            (
                "Assessment",
                "Left hip pain with weak hip abductors (3+/5) and limited internal rotation; Lower Extremity "
                "Functional Scale 42/80.",
            ),
            (
                "Plan of care",
                "Therapeutic exercise (97110-GP) 2x/week for 6 weeks; goals LEFS 65/80, abductors 4+/5. "
                "Signed by referring physician Dr. Jane Smith, MD on 09/11/2005.",
            ),
            (
                "Treatment today",
                [
                    ["Code", "Description", "Minutes", "Units"],
                    [
                        "97110-GP",
                        "Therapeutic exercise: hip abductor and core strengthening",
                        "30",
                        "2",
                    ],
                ],
            ),
        ],
        "Electronically signed: Sam Lee, PT, DPT - 09/11/2005",
    )

    # ---- S4 and S5: Jane M Doe (spouse of Joe Doe, AnyHealth Premium), 2025 ----
    jane = [
        ("Patient", "Jane M Doe"),
        ("DOB", "02/14/1967"),
        ("Insured ID", "123456789A (AnyHealth Premium)"),
    ]
    f["s5_note"] = EVIDENCE / "S5_Jane_Doe_pulmonology_visit_2025-01-07.pdf"
    document(
        f["s5_note"],
        "Any City Medical Group · Pulmonology · NPI 1234567893",
        "Office Visit Note",
        jane
        + [
            ("Rendering provider", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Referring provider", f"Alejandro Rosalez, MD (NPI {REFERRING_NPI})"),
            ("Date of service", "01/07/2025 · in-person office visit (POS 11)"),
        ],
        [
            (
                "Chief complaint",
                "Worsening shortness of breath and wheeze for 2 weeks; onset of exacerbation 12/20/2024.",
            ),
            (
                "History",
                "Known COPD (J44.9) with asthma (J45.909), former smoker (30 pack-years, quit 2015). Using rescue "
                "inhaler 4-5 times daily. No fever. No hospitalization.",
            ),
            (
                "Exam",
                "SpO2 93% on room air, RR 20, diffuse expiratory wheeze, prolonged expiration, no accessory muscle use.",
            ),
            (
                "Medical decision making (moderate)",
                "Two chronic illnesses with exacerbation (COPD, asthma). Spirometry pre/post bronchodilator performed today in "
                "office to assess reversibility (separate report). Prescription drug management: start budesonide/formoterol "
                "160/4.5 two puffs twice daily, 5-day prednisone burst. The E/M service is significant and separately "
                "identifiable from the spirometry test (modifier 25).",
            ),
            (
                "Services today",
                [
                    ["CPT", "Description", "Diagnoses", "Units"],
                    [
                        "99214-25",
                        "Established patient office visit, moderate MDM",
                        "J44.9, J45.909",
                        "1",
                    ],
                    ["94060", "Spirometry pre- and post-bronchodilator", "J44.9", "1"],
                ],
            ),
            ("Plan", "Follow up in 4 weeks; return precautions reviewed."),
        ],
        "Electronically signed: Joe Smith, MD - 01/07/2025",
    )
    f["s5_spiro"] = EVIDENCE / "S5_Jane_Doe_spirometry_report_2025-01-07.pdf"
    document(
        f["s5_spiro"],
        "Any City Medical Group · Pulmonary Function Lab",
        "Spirometry Report (CPT 94060)",
        jane
        + [
            ("Date of test", "01/07/2025"),
            ("Ordering/interpreting", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Indication", "COPD with asthma, acute exacerbation (J44.9, J45.909)"),
        ],
        [
            (
                "Results",
                [
                    [
                        "Measure",
                        "Pre",
                        "Post (albuterol 400 mcg)",
                        "% predicted (pre)",
                        "Change",
                    ],
                    ["FVC (L)", "2.61", "2.84", "82%", "+9%"],
                    ["FEV1 (L)", "1.42", "1.63", "58%", "+15% (210 mL)"],
                    ["FEV1/FVC", "0.54", "0.57", "-", "-"],
                ],
            ),
            (
                "Interpretation",
                "Moderate obstruction (FEV1 58% predicted) with significant bronchodilator response "
                "(+15%, +210 mL), consistent with COPD-asthma overlap. Test quality: grade A.",
            ),
        ],
        "Electronically signed: Joe Smith, MD - 01/07/2025",
    )

    f["s4_note"] = EVIDENCE / "S4_Jane_Doe_visit_and_testing_2025.pdf"
    document(
        f["s4_note"],
        "Any City Medical Group · NPI 1234567893",
        "Visit Notes and Test Results (Jan-Mar 2025)",
        jane + [("Rendering provider", f"Joe Smith, MD (NPI {RENDERING_NPI})")],
        [
            (
                "01/07/2025 - Office visit (in person, POS 11)",
                "COPD (J44.9) with asthma (J45.909) follow-up; diabetes (E11.29) with microalbuminuria. Moderate MDM. "
                "Note: visit was in person in the office; no telehealth was used.",
            ),
            (
                "02/06/2025 and 02/07/2025 - Spirometry",
                "Pre/post bronchodilator spirometry on 02/06 (FEV1 60% predicted). Test repeated on 02/07 because the first "
                "session did not meet acceptability criteria (technical component only, interpreted by outside "
                "pulmonologist).",
            ),
            (
                "03/06/2025 - 03/09/2025 - Mechanical chest wall oscillation at home (POS 12)",
                "Vest therapy sessions performed in the patient's home by office staff, 1 session per day. Indication "
                "documented as asthma symptom control. No documentation of daily sputum production or bronchiectasis.",
            ),
        ],
        "Electronically signed: Joe Smith, MD - 03/20/2025",
    )
    f["s4_lab"] = EVIDENCE / "S4_Jane_Doe_urine_albumin_lab_report.pdf"
    document(
        f["s4_lab"],
        "Any City Medical Group · In-office laboratory (CLIA 05D1234567)",
        "Laboratory Report - Urine Albumin (CPT 82043)",
        jane + [("Indication", "Type 2 diabetes with diabetic kidney complication (E11.29)")],
        [
            (
                "Results",
                [
                    ["Collected", "Test", "Result", "Reference"],
                    [
                        "03/15/2025",
                        "Urine albumin, quantitative",
                        "142 mg/L",
                        "< 30 mg/L",
                    ],
                    [
                        "03/19/2025",
                        "Urine albumin, quantitative (repeat, modifier 91)",
                        "128 mg/L",
                        "< 30 mg/L",
                    ],
                ],
            ),
            (
                "Comment",
                "Repeat on 03/19 to confirm persistent albuminuria. Only 2 specimens were collected; no other "
                "urine albumin tests were performed between 03/15 and 03/19.",
            ),
        ],
        "Electronically reviewed: Joe Smith, MD - 03/20/2025",
    )
    return f


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean = OUT / "S5_clean_claim_form.pdf"
    build_clean_form(FORMS / "sample4_cms-1500-02-12.pdf", clean)
    clean_s6 = OUT / "S6_clean_claim_form_2025-01-21.pdf"
    build_clean_form(
        FORMS / "sample4_cms-1500-02-12.pdf",
        clean_s6,
        S6_OVERRIDES,
        account="JD-20250121",
    )
    ev = make_evidence()
    rel = lambda p: str(p.relative_to(REPO))  # noqa: E731
    scenarios = [
        {
            "id": "S1",
            "title": "Plus: chiropractic, acupuncture, hip X-ray, massage - with notes and X-ray report",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(FORMS / "sample1_cms-1500-P.pdf"), "type": "CMS1500"},
                {"path": rel(ev["s1_notes"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s1_xray"]), "type": "LAB_REPORT"},
            ],
            "expected": "Not approved. Acupuncture excluded on Plus (CARC 96); hip X-ray not supported by a back "
            "diagnosis (MP-204); chiropractic and massage supported by notes; form data issues (POS 'A').",
        },
        {
            "id": "S2",
            "title": "Premium: PT, hip arthrocentesis with fluoroscopy, lumbar X-ray - with procedure and PT notes",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(FORMS / "sample2_cms-1500-P.pdf"), "type": "CMS1500"},
                {"path": rel(ev["s2_ortho"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s2_pt"]), "type": "MEDICAL_RECORD"},
            ],
            "expected": "Injection, fluoroscopy and PT supported by documentation; lumbar X-ray questioned against hip "
            "diagnosis; form data issues keep it in review.",
        },
        {
            "id": "S3",
            "title": "Standard: cardiac testing and supplies - NO evidence (intentionally missing)",
            "provider_id": "PRV-1002",
            "documents": [{"path": rel(FORMS / "sample3_cms-1500-P.pdf"), "type": "CMS1500"}],
            "expected": "PEND: no supporting documentation (CARC 252 / M127); echo and stress test need prior "
            "authorization on Standard (AP-110).",
        },
        {
            "id": "S4",
            "title": "Premium: COPD/diabetes 02-12 form - with visit notes and lab report",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(FORMS / "sample4_cms-1500-02-12.pdf"), "type": "CMS1500"},
                {"path": rel(ev["s4_note"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s4_lab"]), "type": "LAB_REPORT"},
            ],
            "expected": "Not approved. Line 1 telehealth modifier 95 contradicted by in-person note; line 4 home (POS 12) "
            "chest wall oscillation for asthma excluded/not necessary; line 3 bills 5 units but only 2 "
            "specimens documented.",
        },
        {
            "id": "S5",
            "title": "Premium: clean COPD visit + spirometry - with visit note and spirometry report",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(clean), "type": "CMS1500"},
                {"path": rel(ev["s5_note"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s5_spiro"]), "type": "LAB_REPORT"},
            ],
            "expected": "APPROVE both lines (99214-25 and 94060), total $336.35; human review only if extraction "
            "confidence is low.",
        },
        {
            "id": "S6",
            "title": "Premium: clean follow-up visit 01/21/2025 - NO evidence (intentionally missing)",
            "provider_id": "PRV-1001",
            "documents": [{"path": rel(clean_s6), "type": "CMS1500"}],
            "expected": "PEND: services cannot be verified without records (CARC 252 / M127).",
        },
        {
            "id": "S7",
            "title": "Premium: exact resubmission of S5 (duplicate)",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(clean), "type": "CMS1500"},
                {"path": rel(ev["s5_note"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s5_spiro"]), "type": "LAB_REPORT"},
            ],
            "expected": "DUPLICATE_SERVICE on both lines. PEND while S5 is still in review (possible duplicate, AP-130); "
            "DENY CARC 18 once S5 has been finalized. No resubmission code in item 22.",
        },
    ]
    (OUT / "scenarios.json").write_text(json.dumps({"scenarios": scenarios}, indent=2))
    print(f"Wrote {clean.relative_to(REPO)}, {len(ev)} evidence documents and scenarios.json")


if __name__ == "__main__":
    main()

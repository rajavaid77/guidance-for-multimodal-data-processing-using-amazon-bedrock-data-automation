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

    # ---- S4B: supplemental evidence for the S4 claim (Jane Doe, Premium). The S4 claim form is submitted without
    # evidence; these two documents are what a provider would add. They support line 1 (in-person visit, 99214) and
    # explain the two spirometry sessions. They do not make S4 approvable: the form still has blank item 3 / 33a, an
    # invalid referring NPI, modifier 95 with POS 11, and a home-service line that the plan excludes.
    f["s4b_visit"] = EVIDENCE / "S4B_Jane_Doe_office_visit_2025-01-07.pdf"
    document(
        f["s4b_visit"],
        "Any City Medical Group · NPI 1234567893",
        "Office Visit Progress Note",
        jane
        + [
            ("Date of service", "01/07/2025"),
            ("Place of service", "11 - Office (in person). No telehealth was used."),
            ("Rendering provider", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Visit type", "Established patient, follow-up. Total time on the date of service: 35 minutes."),
        ],
        [
            (
                "Chief complaint",
                "Follow-up of COPD with asthma overlap and type 2 diabetes with kidney involvement. Reports increased "
                "morning cough and wheeze over the past 3 weeks, rescue inhaler use about 4 times a week.",
            ),
            (
                "Assessment",
                "1. COPD (J44.9), symptoms worsened from baseline.<br/>2. Asthma, unspecified (J45.909).<br/>"
                "3. Type 2 diabetes with other diabetic kidney complication (E11.29), microalbuminuria on prior "
                "results; repeat urine albumin ordered.",
            ),
            (
                "Medical decision making",
                "Moderate. One chronic illness with exacerbation (COPD) and a second chronic illness under "
                "surveillance (diabetic kidney disease), with prescription drug management.",
            ),
            (
                "Plan",
                "Increase the long-acting bronchodilator dose; continue the inhaled corticosteroid. Order pre/post "
                "bronchodilator spirometry (technical component performed in this office, interpreted by an outside "
                "pulmonologist) and urine albumin testing in March. Return in 8 weeks.",
            ),
            (
                "Procedures this date",
                "None. No separately billed test or procedure was performed on 01/07/2025.",
            ),
        ],
        "Electronically signed: Joe Smith, MD - 01/07/2025",
    )
    f["s4b_spiro"] = EVIDENCE / "S4B_Jane_Doe_spirometry_report_2025-02-06_07.pdf"
    document(
        f["s4b_spiro"],
        "Any City Medical Group · Pulmonary function laboratory",
        "Spirometry Report - Pre/Post Bronchodilator (CPT 94060, technical component)",
        jane
        + [
            ("Indication", "COPD (J44.9) with asthma overlap (J45.909); symptom worsening noted at the 01/07/2025 visit"),
            ("Ordering physician", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Interpretation", "Outside pulmonologist (professional component billed separately by that provider)"),
        ],
        [
            (
                "Sessions",
                [
                    ["Date", "Session", "Quality grade", "Usable for interpretation"],
                    [
                        "02/06/2025",
                        "1",
                        "F - patient cough during the first second of exhalation; repeatability not met",
                        "No",
                    ],
                    [
                        "02/07/2025",
                        "2",
                        "A - acceptability and repeatability criteria met",
                        "Yes",
                    ],
                ],
            ),
            (
                "Results (session 2, 02/07/2025)",
                [
                    ["Measure", "Pre-bronchodilator", "Post-bronchodilator", "Change"],
                    ["FEV1", "1.62 L (51% predicted)", "1.90 L (60% predicted)", "+280 mL (+17%)"],
                    ["FVC", "2.78 L (73% predicted)", "2.95 L (77% predicted)", "+170 mL (+6%)"],
                    ["FEV1/FVC", "0.58", "0.64", ""],
                ],
            ),
            (
                "Reason for the second session",
                "The 02/06/2025 session was not usable because the acceptability criteria were not met, so the test "
                "was repeated the next day. Only the 02/07/2025 session was interpreted.",
            ),
            (
                "Impression",
                "Moderate obstruction with a significant bronchodilator response, consistent with COPD with an "
                "asthmatic component.",
            ),
        ],
        "Electronically signed: Joe Smith, MD - 02/07/2025",
    )
    return f


# ----------------------------------------------------------------------------------------------------------------
# S8: complete claim pack (fully filled CMS-1500 + ID/insurance/Rx/hospital/clinical/billing/bank documents).
# Visit 04/15/2025 (in person, POS 11). Hospital stay 03/24-03/28/2025. Every person, number and business is fictional.
# ----------------------------------------------------------------------------------------------------------------
S8_DOS = "04/15/2025"
S8_ACCOUNT = "JD-20250415"
S8_COPAY_CENTS = 1000  # AnyHealth Premium in-network office visit co-pay: $10 (Schedule of Benefits, section 2)
HOSPITALIST_NPI = "1306849450"  # Maria Chen, MD (fictional, passes the NPI check digit)
S8_LINES = [  # (CPT, modifier, dx pointer, charge in cents, units, description)
    ("99214", "25", "ABC", 18500, 1, "Established patient office visit, moderate MDM"),
    ("94060", "", "AC", 11200, 1, "Spirometry, pre- and post-bronchodilator"),
    ("82043", "", "B", 3800, 1, "Albumin, urine, quantitative (microalbumin)"),
]
S8_TOTAL_CENTS = sum(line[3] for line in S8_LINES)
SPECIMEN = "SPECIMEN - SYNTHETIC TEST DATA - NOT A VALID DOCUMENT"
DARK_RED = colors.Color(0.6, 0.0, 0.0)

# Existing sample4 values that stay as they are (text, rounded x0); every other Arial value is erased and redrawn.
S8_KEEP = {
    ("123456789A", 448), ("Doe, Jane, M", 70), ("Doe, Joe", 471), ("123 Any Street", 478), ("Any City", 459),
    ("CA", 593), ("11111", 430), ("206", 525), ("550-0199", 551), ("A12345678", 444), ("06", 441), ("03", 461),
    ("1965", 480), ("AnyHealth Premium", 426), ("Signature on File", 456), ("Alejandro Rosalez, MD", 93),
    ("J44.9", 80), ("E11.29", 171), ("J45.909", 264), ("234 Another Any Street, Any Avenue", 71),
    ("AnotherCity", 85), ("CA", 249), ("99999", 76), ("206", 165), ("550-0100", 190),
}  # fmt: skip
S8_TEXT = [  # (x, top, text, size): new values on sample4
    (281, 169, "02", 8), (303, 169, "14", 8), (323, 169, "1967", 8),  # item 3 DOB
    (100, 408, "Signature on File", 8), (324, 403, S8_DOS, 10),  # item 12 + date
    (74, 435, "03", 10), (93, 435, "22", 10), (119, 435, "2025", 10), (172, 435, "431", 8),  # item 14 onset + qualifier
    (66, 458, "DN", 8), (289, 460, REFERRING_NPI, 8),  # item 17 qualifier, 17b
    (66, 722, "98-7654321", 8), (222, 722, S8_ACCOUNT, 8),  # items 25, 26
    (158, 767, S8_DOS, 10), (222, 744, "Any City Medical Group", 8), (222, 755, "500 Health Way", 8),
    (222, 766, "Any City CA 11111", 8), (238, 781, BILLING_NPI, 8),  # items 31 date, 32, 32a
    (418, 744, "Any City Medical Group", 8), (418, 755, "500 Health Way", 8), (418, 766, "Any City CA 11111", 8),
    (531, 735, "206", 8), (556, 735, "555-0123", 8), (432, 781, BILLING_NPI, 8),  # item 33, 33a
]  # fmt: skip
# Item 18 hospitalization dates (From / To): x positions of MM, DD, YYYY
S8_HOSP = [(445, 457, "03"), (466, 457, "24"), (490, 457, "2025"), (547, 457, "03"), (570, 457, "28"), (594, 457, "2025")]
S8_CHECK = [  # boxes to mark with an X
    (276.5, 144, 285.5, 153.5),  # item 1 group health plan
    (347.5, 288.5, 358.5, 299),  # 10a NO
    (347.5, 335.5, 358.5, 346.5),  # 10c NO
    (463.5, 479.5, 474, 491),  # 20 NO
    (190, 719, 200, 729),  # 25 EIN
    (327, 719, 337, 729),  # 27 YES
    (392, 167.5, 402, 177.5),  # 3 sex F
    (326.5, 192.8, 337.5, 203),  # 6 relationship: spouse
    (347.5, 312.5, 358.5, 323),  # 10b NO
    (462.5, 359.7, 473.5, 370.7),  # 11d NO
    (542, 288, 553, 299),  # 11a sex M
]  # fmt: skip


def build_full_form(src: Path, dst: Path) -> None:
    """Fully filled CMS-1500 for S8. The sample's filled-in layer (a Fill & Sign form XObject with every sample value,
    check mark and signature image, and a pencil annotation) is removed from the page, then all values are drawn again
    as real text so the text layer holds exactly the story values (no hidden sample text under white patches)."""
    with pdfplumber.open(src) as pdf:
        page = pdf.pages[0]
        width, height = page.width, page.height
        words = page.extract_words(keep_blank_chars=True, extra_attrs=["fontname"])
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))

    def put(x: float, top: float, text: str, size: float = 8, right: bool = False) -> None:
        c.setFont("Helvetica", size)
        y = height - top - size + 1.5
        c.drawRightString(x, y, text) if right else c.drawString(x, y, text)

    for w in words:  # sample values that already match the story are redrawn unchanged
        if "Arial" in w["fontname"] and ("DTELUR" in w["fontname"] or (w["text"], round(w["x0"])) in S8_KEEP):
            size = w["bottom"] - w["top"]
            c.setFont("Helvetica", size)
            c.drawString(w["x0"], height - w["bottom"] + 0.21 * size + 0.8, w["text"])  # keep the original baseline
    for x, top, text, size in S8_TEXT:
        put(x, top, text, size)
    for x, top, text in S8_HOSP:
        put(x, top, text, 8)
    tops = [579, 603.5, 627.5]
    for (cpt, mod, ptr, cents, units, _d), t in zip(S8_LINES, tops):
        month, day, year = S8_DOS.split("/")
        for x, v in ((66, month), (85, day), (102, year), (130, month), (149, day), (168, year)):
            put(x, t, v)
        put(194, t, "11")
        put(238, t, cpt)
        put(289, t, mod)
        put(380, t, ptr)
        put(437, t, f"{cents // 100}", right=True)
        put(459, t, f"{cents % 100:02d}")
        put(482, t, str(units))
        put(545, t, RENDERING_NPI)
    put(464, 722, f"{S8_TOTAL_CENTS // 100}", right=True)
    put(476, 722, f"{S8_TOTAL_CENTS % 100:02d}")  # item 28
    put(537, 722, f"{S8_COPAY_CENTS // 100}", right=True)
    put(547, 722, f"{S8_COPAY_CENTS % 100:02d}")  # item 29
    c.setFont("Times-Italic", 12)
    c.drawString(73, height - 778, "Joe Smith MD")  # item 31 signature
    c.setLineWidth(1.2)
    c.setStrokeColor(colors.black)
    for x0, top, x1, bottom in S8_CHECK:
        c.line(x0 + 1.5, height - top - 1.5, x1 - 1.5, height - bottom + 1.5)
        c.line(x0 + 1.5, height - bottom + 1.5, x1 - 1.5, height - top - 1.5)
    c.save()

    overlay = PdfReader(io.BytesIO(buf.getvalue()))
    writer = PdfWriter(clone_from=str(src))
    while len(writer.pages) > 1:
        writer.remove_page(len(writer.pages) - 1)  # page 2 of the sample is blank
    form = writer.pages[0]
    if "/Annots" in form:
        del form["/Annots"]  # pencil (ink) annotation dot near item 12
    from pypdf.generic import ContentStream

    stream = ContentStream(form.get_contents(), writer)
    stream.operations = [
        (ops, op) for ops, op in stream.operations if not (op == b"Do" and ops and str(ops[0]) in ("/Fm0", "/Im1", "/Im2"))
    ]  # keep the form artwork and QR code (/Im0)
    form.replace_contents(stream)
    form.merge_page(overlay.pages[0])
    with dst.open("wb") as fh:
        writer.write(fh)


def _specimen(c: canvas.Canvas, w: float, h: float) -> None:
    """Border + top/bottom bands marking an ID-type page as a synthetic specimen."""
    c.setStrokeColor(DARK_RED)
    c.setLineWidth(1.5)
    c.rect(18, 18, w - 36, h - 36)
    c.setFillColor(DARK_RED)
    c.rect(18, h - 38, w - 36, 20, fill=1, stroke=0)
    c.rect(18, 18, w - 36, 20, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(w / 2, h - 32, SPECIMEN)
    c.drawCentredString(w / 2, 25, SPECIMEN)
    c.setFillColor(colors.black)


def _silhouette(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(colors.Color(0.85, 0.87, 0.9))
    c.setStrokeColor(colors.grey)
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.Color(0.55, 0.58, 0.63))
    c.circle(x + w / 2, y + h * 0.65, w * 0.2, fill=1, stroke=0)
    p = c.beginPath()
    p.moveTo(x + w * 0.12, y)
    p.curveTo(x + w * 0.12, y + h * 0.4, x + w * 0.88, y + h * 0.4, x + w * 0.88, y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x + w / 2, y - 8, "PLACEHOLDER - NOT A PHOTO")


def _fields(c: canvas.Canvas, x: float, y: float, rows: list[tuple[str, str, float]], gap: float = 26) -> float:
    """Labelled fields, one per row: (label, value, x offset). Returns the y after the last row."""
    for label, value, dx in rows:
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.Color(0.3, 0.3, 0.3))
        c.drawString(x + dx, y + 9, label)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + dx, y - 2, value)
        y -= 0 if dx else gap
    return y


def make_id_card(path: Path, kind: str) -> None:
    """Placeholder driver's license (Jane) or state identification card (Joe). Generic design, not any real state's."""
    lic = kind == "license"
    w, h = letter
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Driver License - Jane M Doe" if lic else "State Identification Card - Joe Doe")
    _specimen(c, w, h)
    x0, y0, cw, ch = 72, h - 120 - 3.9 * inch, 6.2 * inch, 3.9 * inch
    c.setFillColor(colors.Color(0.93, 0.96, 0.99))
    c.setStrokeColor(colors.Color(0.1, 0.2, 0.45))
    c.setLineWidth(2)
    c.roundRect(x0, y0, cw, ch, 12, fill=1, stroke=1)
    c.setFillColor(colors.Color(0.1, 0.2, 0.45))
    c.rect(x0, y0 + ch - 44, cw, 44, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(x0 + 14, y0 + ch - 24, "STATE OF ANYSTATE")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + cw - 14, y0 + ch - 24, "DRIVER LICENSE" if lic else "IDENTIFICATION CARD")
    c.setFillColor(colors.black)
    _silhouette(c, x0 + 14, y0 + ch - 190, 100, 125)
    if lic:
        d = dict(num="X000-000-0000", last="DOE", first="JANE M", dob="02/14/1967", iss="06/12/2022",
                 exp="02/14/2028", addr="234 ANOTHER ANY STREET, ANY AVENUE", city="ANOTHERCITY, CA 99999",
                 sex="F", hgt="5'-06\"", wgt="140 lb", eyes="BRN", hair="BRN", cls="C")  # fmt: skip
    else:
        d = dict(num="X000-000-0001", last="DOE", first="JOE", dob="06/03/1965", iss="03/09/2021",
                 exp="06/03/2029", addr="123 ANY STREET", city="ANY CITY, CA 11111",
                 sex="M", hgt="5'-11\"", wgt="185 lb", eyes="BLU", hair="GRY", cls="NONE")  # fmt: skip
    fx = x0 + 130
    top = y0 + ch - 62
    _fields(c, fx, top, [("DLN" if lic else "ID NO.", d["num"], 0)])
    _fields(c, fx, top - 28, [("1 LAST NAME", d["last"], 0)])
    _fields(c, fx, top - 56, [("2 FIRST NAME / MIDDLE", d["first"], 0)])
    _fields(c, fx, top - 84, [("8 ADDRESS", d["addr"], 0)])
    c.setFont("Helvetica-Bold", 10)
    c.drawString(fx, top - 98, d["city"])
    _fields(c, fx, top - 124, [("3 DOB", d["dob"], 0)])
    _fields(c, fx + 110, top - 124, [("15 SEX", d["sex"], 0)])
    _fields(c, fx + 160, top - 124, [("16 HGT", d["hgt"], 0)])
    _fields(c, fx + 225, top - 124, [("17 WGT", d["wgt"], 0)])
    _fields(c, fx, top - 152, [("4a ISS", d["iss"], 0)])
    _fields(c, fx + 110, top - 152, [("4b EXP", d["exp"], 0)])
    _fields(c, fx + 225, top - 152, [("18 EYES", d["eyes"], 0)])
    _fields(c, x0 + 14, y0 + 58, [("9 CLASS", d["cls"], 0)])
    _fields(c, x0 + 70, y0 + 58, [("19 HAIR", d["hair"], 0)])
    _fields(c, fx, y0 + 36, [("12 RESTR", "NONE", 0)])
    _fields(c, fx + 110, y0 + 36, [("END", "NONE", 0)])
    c.setFont("Helvetica-Oblique", 11)
    c.drawString(x0 + 14, y0 + 20, "Jane M Doe" if lic else "Joe Doe")
    c.setFont("Helvetica", 6)
    c.drawString(x0 + 14, y0 + 10, "SIGNATURE (SYNTHETIC)")
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(DARK_RED)
    c.drawRightString(x0 + cw - 14, y0 + 10, SPECIMEN)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y0 - 30, "Driver license - front" if lic else "State identification card - front")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawCentredString(w / 2, 50, "Synthetic document generated for software testing. Not a real identification document.")
    c.save()


def make_insurance_card(path: Path) -> None:
    w, h = letter
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("AnyHealth Premium member ID card")
    _specimen(c, w, h)
    navy = colors.Color(0.05, 0.25, 0.45)
    cw, ch, x0 = 6.0 * inch, 3.05 * inch, (w - 6.0 * inch) / 2

    def card(y: float, label: str) -> None:
        c.setFillColor(colors.Color(0.96, 0.98, 1))
        c.setStrokeColor(navy)
        c.setLineWidth(1.5)
        c.roundRect(x0, y, cw, ch, 10, fill=1, stroke=1)
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 8)
        c.drawString(x0, y + ch + 5, label)
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(DARK_RED)
        c.drawRightString(x0 + cw - 10, y + 6, SPECIMEN)
        c.setFillColor(colors.black)

    yf = h - 70 - ch
    card(yf, "Member ID card - FRONT")
    c.setFillColor(navy)
    c.rect(x0, yf + ch - 40, cw, 40, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x0 + 14, yf + ch - 27, "AnyHealth")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(x0 + cw - 14, yf + ch - 26, "PREMIUM  PPO")
    c.setFillColor(colors.black)
    top = yf + ch - 62
    rows = [
        (0, 0, "Member Name (Subscriber)", "Joe Doe"), (190, 0, "Dependent / Covered Member", "Jane M Doe"),
        (0, 34, "Member ID", "123456789A"), (190, 34, "Group Number", "A12345678"),
        (0, 68, "Plan", "AnyHealth Premium"), (190, 68, "Effective Date", "01/01/2024"),
    ]  # fmt: skip
    for dx, dy, label, value in rows:
        _fields(c, x0 + 14 + dx, top - dy, [(label, value, 0)])
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x0 + 14, yf + 62, "Copays:")
    c.setFont("Helvetica", 8)
    c.drawString(x0 + 14, yf + 50, "Office visit / specialist  $10    Diagnostic X-ray and lab  $10")
    c.drawString(x0 + 14, yf + 39, "Urgent care  $30    Emergency room  $150    Deductible (individual)  $2,000")
    c.drawString(x0 + 14, yf + 28, "Rx  Generic $10 / Brand $35   RxBIN 000000   RxPCN ANYRX   RxGrp A12345678")

    yb = yf - ch - 50
    card(yb, "Member ID card - BACK")
    c.setFillColor(colors.black)
    c.rect(x0, yb + ch - 36, cw, 20, fill=1, stroke=0)
    lines = [
        "Member services (24/7): 1-800-555-0100       TTY: 711",
        "Provider services / eligibility: 1-800-555-0101       Prior authorization: 1-800-555-0102",
        "Submit medical claims to: AnyHealth Claims, P.O. Box 0000, Any City, CA 11111",
        "Electronic payer ID: 00000       Website: www.anyhealth.example",
        "Pharmacy help desk: 1-800-555-0103       Behavioral health: 1-800-555-0104",
        "This card does not guarantee coverage or payment. Present it at every visit.",
        "In an emergency call 911 or go to the nearest emergency room.",
    ]
    c.setFont("Helvetica", 8)
    for i, t in enumerate(lines):
        c.drawString(x0 + 14, yb + ch - 56 - i * 15, t)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawCentredString(w / 2, 50, "Synthetic document generated for software testing. Not a real insurance card.")
    c.save()


def make_rx_label(path: Path) -> None:
    w, h = letter
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Prescription label - Jane M Doe")
    lw, lh = 4.6 * inch, 5.3 * inch
    x0, y0 = (w - lw) / 2, h - 80 - lh
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.5)
    c.roundRect(x0, y0, lw, lh, 8, fill=1, stroke=1)
    c.setFillColor(colors.Color(0.0, 0.4, 0.25))
    c.rect(x0, y0 + lh - 52, lw, 52, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(x0 + lw / 2, y0 + lh - 24, "ANY CITY PHARMACY")
    c.setFont("Helvetica", 8)
    c.drawCentredString(x0 + lw / 2, y0 + lh - 38, "100 Main Street, Any City, CA 11111  |  Phone (206) 555-0150")
    c.drawCentredString(x0 + lw / 2, y0 + lh - 48, "Open daily 8am-9pm")
    c.setFillColor(colors.black)
    y = y0 + lh - 74

    def row(label: str, value: str, size: float = 10, bold: bool = True) -> None:
        nonlocal y
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawString(x0 + 14, y, label)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x0 + 14, y - 12, value)
        y -= 32

    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0 + 14, y, "Rx 0000451")
    c.setFont("Helvetica", 9)
    c.drawRightString(x0 + lw - 14, y, "Fill date: 04/15/2025")
    y -= 24
    row("PATIENT", "JANE M DOE", 12)
    row("ADDRESS", "234 Another Any Street, Any Avenue, AnotherCity, CA 99999", 8, False)
    row("DRUG / STRENGTH", "BUDESONIDE-FORMOTEROL 160 MCG/4.5 MCG INHALER", 10)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawString(x0 + 14, y, "DIRECTIONS")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0 + 14, y - 13, "INHALE 2 PUFFS BY MOUTH TWICE DAILY. RINSE MOUTH")
    c.drawString(x0 + 14, y - 26, "WITH WATER AFTER EACH USE AND SPIT IT OUT.")
    y -= 50
    c.setFont("Helvetica", 9)
    c.drawString(x0 + 14, y, "QTY: 1 inhaler (120 actuations)")
    c.drawString(x0 + 200, y, "REFILLS: 5 remaining")
    y -= 16
    c.drawString(x0 + 14, y, "PRESCRIBER: JOE SMITH, MD   NPI 1654329873")
    y -= 14
    c.drawString(x0 + 14, y, "Date written: 04/15/2025        Discard after: 04/15/2026")
    y -= 14
    c.drawString(x0 + 14, y, "Plan: AnyHealth Premium  |  ID 123456789A  |  Grp A12345678")
    y -= 14
    c.drawString(x0 + 14, y, "Pharmacist: A. Lopez, RPh")
    y -= 22
    for i, (txt, col) in enumerate(
        [("CHRONIC USE", colors.Color(0.85, 0.1, 0.1)), ("MAY CAUSE HOARSENESS", colors.Color(0.9, 0.6, 0.0)),
         ("DO NOT STOP SUDDENLY", colors.Color(0.2, 0.3, 0.8))]
    ):  # fmt: skip
        bx = x0 + 14 + i * 104
        c.setFillColor(col)
        c.rect(bx, y - 4, 100, 15, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(bx + 50, y, txt)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 6.5)
    c.drawString(x0 + 14, y0 + 14, "Keep out of reach of children. Federal law prohibits transfer to anyone other than the patient.")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawCentredString(w / 2, 50, "Synthetic document generated for software testing. Not a real prescription label.")
    c.save()


def make_bank_statement(path: Path) -> None:
    w, h = letter
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Any Bank checking statement - April 2025")
    _specimen(c, w, h)
    navy = colors.Color(0.05, 0.25, 0.45)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(50, h - 78, "ANY BANK")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(50, h - 92, "Checking Account Statement  |  Member FDIC (synthetic)  |  1-800-555-0120")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, h - 120, "JANE M DOE")
    c.setFont("Helvetica", 10)
    c.drawString(50, h - 133, "234 Another Any Street, Any Avenue")
    c.drawString(50, h - 146, "AnotherCity, CA 99999")
    c.drawString(340, h - 120, "Statement period: 04/01/2025 - 04/30/2025")
    c.drawString(340, h - 133, "Account number: 0000-1234 (Everyday Checking)")
    c.drawString(340, h - 146, "Page 1 of 1")
    tx = [  # (date, description, amount in cents; negative = withdrawal)
        ("04/03", "DIRECT DEPOSIT - ANYCO PAYROLL", 215000),
        ("04/04", "FRESH MART #112 GROCERIES", -8642),
        ("04/05", "ANY CITY UTILITIES - ELECTRIC", -11230),
        ("04/10", "FRESH MART #112 GROCERIES", -6418),
        ("04/15", "DIRECT DEPOSIT - ANYCO PAYROLL", 215000),
        ("04/15", "ANY CITY MEDICAL GROUP - COPAY 04/15/2025", -S8_COPAY_CENTS),
        ("04/15", "ANY CITY PHARMACY #0415", -3500),
        ("04/17", "STREAMINGCO SUBSCRIPTION", -1599),
        ("04/21", "GASSTOP #33 FUEL", -4275),
        ("04/25", "ANY CITY PROPERTY MGMT - RENT", -145000),
    ]
    start = 341257
    bal = start
    rows = [["Date", "Description", "Withdrawals", "Deposits", "Balance"], ["04/01", "Beginning balance", "", "", f"{start / 100:,.2f}"]]
    for d, desc, amt in tx:
        bal += amt
        rows.append([d, desc, f"{-amt / 100:,.2f}" if amt < 0 else "", f"{amt / 100:,.2f}" if amt > 0 else "", f"{bal / 100:,.2f}"])
    rows.append(["04/30", "Ending balance", "", "", f"{bal / 100:,.2f}"])
    dep = sum(a for _, _, a in tx if a > 0)
    wd = -sum(a for _, _, a in tx if a < 0)
    summ = Table(
        [["Beginning balance", "Total deposits", "Total withdrawals", "Ending balance"],
         [f"${start / 100:,.2f}", f"${dep / 100:,.2f}", f"${wd / 100:,.2f}", f"${bal / 100:,.2f}"]],
        colWidths=[1.7 * inch] * 4,
    )  # fmt: skip
    summ.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                              ("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold")]))  # fmt: skip
    summ.wrapOn(c, w, h)
    summ.drawOn(c, 50, h - 205)
    tbl = Table(rows, colWidths=[0.6 * inch, 3.1 * inch, 1.0 * inch, 1.0 * inch, 1.1 * inch])
    style = [("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
             ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]  # fmt: skip
    tbl.setStyle(TableStyle(style))
    tw, th = tbl.wrapOn(c, w, h)
    tbl.drawOn(c, 50, h - 225 - th)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(50, 62, "Questions about this statement? Call 1-800-555-0120. Synthetic document generated for software testing.")
    c.save()


def make_s8() -> dict[str, Path]:
    """Create the S8 form + individual evidence PDFs in OUT/EVIDENCE and merge the pack into OUT."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    f: dict[str, Path] = {"form": OUT / "S8_claim_form_2025-04-15.pdf"}
    build_full_form(FORMS / "sample4_cms-1500-02-12.pdf", f["form"])
    names = ["insurance_card", "drivers_license", "state_id", "prescription_label", "discharge_summary",
             "office_visit_note", "spirometry_report", "urine_albumin_report", "provider_invoice", "bank_statement"]  # fmt: skip
    for i, n in enumerate(names, start=1):
        f[n] = EVIDENCE / f"S8_{i}_{n}.pdf"
    make_insurance_card(f["insurance_card"])
    make_id_card(f["drivers_license"], "license")
    make_id_card(f["state_id"], "state_id")
    make_rx_label(f["prescription_label"])
    make_bank_statement(f["bank_statement"])

    jane = [("Patient", "Jane M Doe"), ("DOB", "02/14/1967"), ("Insured ID", "123456789A (AnyHealth Premium)")]
    clinic = "Any City Medical Group · NPI 1234567893"
    document(
        f["discharge_summary"],
        "Any City General Hospital",
        "Hospital Discharge Summary",
        [
            ("Hospital name", "Any City General Hospital"),
            ("Hospital contact", "1000 Hospital Drive, Any City, CA 11111 · Phone (206) 555-0190 · Fax (206) 555-0191"),
            ("Admitted date", "03-24-2025"),
            ("Discharged date", "03-28-2025"),
            ("Discharged to", "Home (self-care) with outpatient follow-up"),
            ("Patient name", "Jane M Doe"),
            ("Gender", "Female"),
            ("Patient ID (MRN)", "MRN-00458213"),
            ("Date of birth", "02/14/1967"),
            ("Insured ID", "123456789A (AnyHealth Premium)"),
            ("Provider name", "Maria Chen, MD (attending hospitalist)"),
            ("Provider ID (NPI)", HOSPITALIST_NPI),
        ],
        [
            (
                "Reported symptoms and history of present illness",
                "58-year-old woman with COPD (J44.9) and asthma (J45.909) and type 2 diabetes with kidney "
                "complication (E11.29). Symptoms began 03/22/2025: worsening shortness of breath, productive cough "
                "and wheeze, rescue inhaler use every 2-3 hours. Admitted 03/24/2025 with SpO2 87% on room air.",
            ),
            (
                "Diagnoses and hospital course",
                "Principal diagnosis: acute exacerbation of COPD. Treated with nebulized bronchodilators, systemic "
                "corticosteroid, antibiotics and supplemental oxygen. Chest X-ray: no pneumonia. Glucose managed "
                "with insulin sliding scale while on steroids. Oxygen weaned off by 03/27/2025.",
            ),
            (
                "Discharge summary and instructions",
                "Discharged 03-28-2025 in stable condition, SpO2 94% on room air. Complete the prednisone taper "
                "and continue the budesonide-formoterol inhaler, two puffs twice daily. Check blood glucose four "
                "times daily while on steroids. Return to the emergency department for worsening breathlessness, "
                "fever or chest pain. Follow-up with Joe Smith, MD (Any City Medical Group) within 2 weeks for "
                "repeat spirometry and diabetes kidney monitoring.",
            ),
        ],
        f"Electronically signed: Maria Chen, MD (NPI {HOSPITALIST_NPI}) - 03/28/2025",
    )
    document(
        f["office_visit_note"],
        clinic,
        "Office Visit Progress Note",
        [
            ("Patient", "Jane M Doe · DOB 02/14/1967 · Insured ID 123456789A (AnyHealth Premium)"),
            ("Date of service", S8_DOS),
            ("Place of service", "11 - Office. In-person visit. No telehealth was used."),
            ("Rendering provider", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Referring provider", f"Alejandro Rosalez, MD (NPI {REFERRING_NPI})"),
            ("Visit type", "Established patient, post-hospitalization follow-up. Time spent on the E/M, excluding the "
             "separately reported tests: 35 minutes."),
        ],  # fmt: skip
        [
            (
                "Chief complaint and history",
                "Follow-up after hospitalization 03/24/2025-03/28/2025 for COPD exacerbation (symptom onset "
                "03/22/2025). Residual cough, improved dyspnea, rescue inhaler about once daily. Also reviewed "
                "diabetic kidney disease and glucose control after steroid therapy. Seen in person in the office. "
                "Exam: SpO2 95% room air, RR 18, mild end-expiratory wheeze, BP 128/76, no edema.",
            ),
            (
                "Assessment",
                "1. COPD (J44.9), recent exacerbation resolved, now stable on the current regimen.<br/>2. Type 2 diabetes with diabetic "
                "kidney complication (E11.29), glucose elevated on steroids, urine albumin due.<br/>"
                "3. Asthma, unspecified, uncomplicated (J45.909).",
            ),
            (
                "Medical decision making (moderate) and modifier 25",
                "One chronic illness with exacerbation (COPD) and a second chronic illness needing medication "
                "adjustment (diabetes with kidney complication), with prescription drug management. The evaluation "
                "and management service is significant and separately identifiable from the same-day tests: "
                "post-hospital medication reconciliation, steroid taper review, inhaler regimen change and diabetes "
                "management were performed in addition to the tests (modifier 25 on 99214).",
            ),
            (
                "Tests performed in this office today",
                "94060 spirometry pre/post bronchodilator (J44.9, J45.909), 1 unit, separate report. 82043 urine "
                "albumin, 1 specimen, performed in the office laboratory (E11.29), separate report.",
            ),
            (
                "Plan",
                "Continue budesonide-formoterol 160/4.5 mcg, two puffs twice daily (prescription filled 04/15/2025). "
                "Complete steroid taper, resume home glucose log. Return in 8 weeks. Patient co-pay of $10.00 "
                "collected at check-in.",
            ),
        ],
        f"Electronically signed: Joe Smith, MD - {S8_DOS}",
    )
    document(
        f["spirometry_report"],
        "Any City Medical Group · Pulmonary Function Lab",
        "Spirometry Report - Pre/Post Bronchodilator (CPT 94060)",
        jane
        + [
            ("Date of test", f"{S8_DOS} (performed in the office)"),
            ("Ordering/interpreting", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
            ("Indication", "COPD (J44.9) with asthma (J45.909), follow-up after hospitalization"),
            ("Sessions", "1 session on 04/15/2025. Test quality: grade A (acceptability and repeatability criteria met)."),
        ],  # fmt: skip
        [
            (
                "Results",
                [
                    ["Measure", "Pre", "Post (albuterol 400 mcg)", "% predicted (pre)", "Change"],
                    ["FVC (L)", "2.72", "2.91", "85%", "+7%"],
                    ["FEV1 (L)", "1.51", "1.72", "61%", "+14% (210 mL)"],
                    ["FEV1/FVC", "0.56", "0.59", "-", "-"],
                ],
            ),
            (
                "Interpretation",
                "Moderate obstruction (FEV1 61% predicted) with a significant bronchodilator response (+14%, "
                "+210 mL), consistent with COPD-asthma overlap. Improved from the pre-admission baseline.",
            ),
        ],
        f"Electronically signed: Joe Smith, MD (interpreting physician) - {S8_DOS}",
    )
    document(
        f["urine_albumin_report"],
        "Any City Medical Group · In-office laboratory (CLIA 05D1234567)",
        "Laboratory Report - Urine Albumin (CPT 82043)",
        jane
        + [
            ("Indication", "Type 2 diabetes with diabetic kidney complication (E11.29)"),
            ("Testing location", "Performed in the office laboratory (CLIA 05D1234567); not sent to an outside lab"),
            ("Ordering physician", f"Joe Smith, MD (NPI {RENDERING_NPI})"),
        ],  # fmt: skip
        [
            (
                "Results",
                [
                    ["Collected", "Test", "Result", "Reference"],
                    [S8_DOS + " 10:15", "Urine albumin, quantitative", "86 mg/L", "< 30 mg/L"],
                ],
            ),
            (
                "Comment",
                "One specimen collected and tested on 04/15/2025. No other urine albumin test was performed on this "
                "date. Persistent albuminuria consistent with diabetic kidney disease.",
            ),
        ],
        f"Electronically reviewed: Joe Smith, MD - {S8_DOS}",
    )
    money = lambda cents: f"${cents / 100:,.2f}"  # noqa: E731
    document(
        f["provider_invoice"],
        clinic + " · Tax ID 98-7654321",
        "Itemized Statement / Invoice",
        [
            ("Invoice number", "INV-20250415-0117"),
            ("Provider", "Any City Medical Group, 500 Health Way, Any City CA 11111 · Phone (206) 555-0123"),
            ("Patient", "Jane M Doe"),
            ("DOB", "02/14/1967"),
            ("Insured / Member ID", "Joe Doe (subscriber) · 123456789A · Group A12345678 · AnyHealth Premium"),
            ("Account number", S8_ACCOUNT),
            ("Date of service", f"{S8_DOS} (office visit, POS 11)"),
            ("Invoice date", S8_DOS),
        ],  # fmt: skip
        [
            (
                "Charges",
                [["Date", "CPT", "Description", "Dx", "Units", "Charge"]]
                + [
                    [S8_DOS, cpt + (f"-{m}" if m else ""), d, "J44.9, E11.29, J45.909" if cpt == "99214"
                     else ("J44.9, J45.909" if cpt == "94060" else "E11.29"), str(u), money(ch)]
                    for cpt, m, _p, ch, u, d in S8_LINES
                ]  # fmt: skip
                + [["", "", "<b>Total charges</b>", "", "", f"<b>{money(S8_TOTAL_CENTS)}</b>"]],
            ),
            (
                "Payments and balance",
                [
                    ["Date", "Description", "Amount"],
                    [S8_DOS, "Patient co-pay received at check-in (debit card)", money(S8_COPAY_CENTS)],
                    ["", "<b>Total patient payments</b>", f"<b>{money(S8_COPAY_CENTS)}</b>"],
                    ["", "Balance billed to AnyHealth Premium (claim submitted)", money(S8_TOTAL_CENTS - S8_COPAY_CENTS)],
                ],
            ),
        ],
        "Remit questions: Any City Medical Group billing office, (206) 555-0123.",
    )
    # pack order: claim form, card, license, state id, Rx, discharge, note, spirometry, urine albumin, invoice, bank
    pack_order = ["form"] + names
    f["pack"] = OUT / "S8_Jane_Doe_complete_claim_pack_2025-04-15.pdf"
    writer = PdfWriter()
    for key in pack_order:
        for page in PdfReader(str(f[key])).pages:
            writer.add_page(page)
    with f["pack"].open("wb") as fh:
        writer.write(fh)
    return f


def s8_pack_pages(f: dict[str, Path]) -> dict[str, str]:
    pages, start = {}, 1
    for key in ["form"] + [k for k in f if k not in ("form", "pack")]:
        n = len(PdfReader(str(f[key])).pages)
        pages[key] = f"{start}" if n == 1 else f"{start}-{start + n - 1}"
        start += n
    return pages


def s8_scenario(f: dict[str, Path]) -> dict:
    rel = lambda p: str(p.relative_to(REPO))  # noqa: E731
    types = {
        "form": "CMS1500", "insurance_card": "INSURANCE_CARD", "drivers_license": "DRIVER_LICENSE", "state_id": "OTHER",
        "prescription_label": "PRESCRIPTION_LABEL", "discharge_summary": "DISCHARGE_SUMMARY",
        "office_visit_note": "MEDICAL_RECORD", "spirometry_report": "LAB_REPORT", "urine_albumin_report": "LAB_REPORT",
        "provider_invoice": "OTHER", "bank_statement": "OTHER",
    }  # fmt: skip
    return {
        "id": "S8",
        "title": "Premium: complete claim pack (fully filled CMS-1500 + insurance card, 2 IDs, Rx label, discharge "
        "summary, visit note, 2 lab reports, invoice, bank statement) for visit 04/15/2025",
        "provider_id": "PRV-1001",
        "documents": [{"path": rel(f["pack"]), "type": "AUTO"}],
        "individual_documents": [{"path": rel(f[k]), "type": t} for k, t in types.items()],
        "pack_pages": s8_pack_pages(f),
        "expected": "APPROVE all 3 lines (99214-25, 94060, 82043), total $335.00, patient co-pay $10.00; human review "
        "only if extraction confidence is low. Upload the pack as one document (BDA splits and classifies it) or the "
        "individual files (max 10 per upload).",
    }


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
    s8 = make_s8()
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
            "id": "S4B",
            "title": "Premium: supplemental evidence for the S4 claim (office visit note + spirometry report)",
            "provider_id": "PRV-1001",
            "documents": [
                {"path": rel(ev["s4b_visit"]), "type": "MEDICAL_RECORD"},
                {"path": rel(ev["s4b_spiro"]), "type": "LAB_REPORT"},
            ],
            "expected": "Upload as ADDITIONAL documents on a pended S4 claim (together with the existing S4 urine "
            "albumin report). Clears NO_EVIDENCE_SUBMITTED and documents an in-person 01/07 visit and the two "
            "spirometry sessions. Still not approvable: S4 item 3 and 33a are blank, referring NPI 0123456789 is "
            "invalid, line 1 has modifier 95 with POS 11, line 3 bills 5 units for 2 specimens, and line 4 (home, "
            "POS 12) is excluded.",
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
        s8_scenario(s8),
    ]
    (OUT / "scenarios.json").write_text(json.dumps({"scenarios": scenarios}, indent=2))
    print(f"Wrote {clean.relative_to(REPO)}, {len(ev)} evidence documents and scenarios.json")


if __name__ == "__main__":
    main()

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, BorderStyle, ShadingType, AlignmentType, PageOrientation,
} = require("docx");

const US_LETTER = { width: 12240, height: 15840 };

function banner(text) {
  return new Paragraph({
    shading: { type: ShadingType.CLEAR, fill: "FFF3CD" },
    border: {
      top: { style: BorderStyle.SINGLE, size: 12, color: "B45309" },
      bottom: { style: BorderStyle.SINGLE, size: 12, color: "B45309" },
      left: { style: BorderStyle.SINGLE, size: 12, color: "B45309" },
      right: { style: BorderStyle.SINGLE, size: 12, color: "B45309" },
    },
    spacing: { before: 100, after: 200 },
    children: [
      new TextRun({ text, bold: true, color: "92400E" }),
    ],
  });
}

function h1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300, after: 150 }, children: [new TextRun({ text })] });
}
function h2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 250, after: 120 }, children: [new TextRun({ text })] });
}
function p(text, opts = {}) {
  return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, ...opts })] });
}
function bullet(text) {
  return new Paragraph({ text, bullet: { level: 0 }, spacing: { after: 60 } });
}

function cell(text, { width, header = false } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header ? { type: ShadingType.CLEAR, fill: "E5E7EB" } : undefined,
    children: [new Paragraph({ children: [new TextRun({ text: String(text), bold: header, size: 18 })] })],
  });
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: headers.map((hTxt, i) => cell(hTxt, { width: widths[i], header: true })) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, { width: widths[i] })) })),
    ],
  });
}

const doc = new Document({
  sections: [
    {
      properties: { page: { size: US_LETTER } },
      children: [
        banner("⚠ SYNTHETIC DEMONSTRATION DOCUMENT — NOT A REAL REGULATION. Entirely fictional, for PARIVART product demonstration only. Not legal advice. Not evidence of any real deficiency. The authority, identifier, dates, requirements and deficiencies below are invented."),

        new Paragraph({ heading: HeadingLevel.TITLE, spacing: { after: 100 }, children: [
          new TextRun({ text: "Notice of Amendment — Labelling and Electronic Instructions for Use" }),
        ]}),
        p("for Class II/III Monitoring and Therapeutic Devices", { italics: true }),

        p("Issuing Authority (fictional): Federal Agency for Demonstrative Device Regulation (\"FADDR\") — invented for this demonstration only, not affiliated with any real regulator.", { bold: false }),
        p("Document identifier (fictional): FADDR-DEMO-2026-0147"),
        p("Publication date (fictional): 2026-09-15      Effective date (fictional): 2027-01-01"),

        h1("1. Summary of the hypothetical regulatory change"),
        p("This fictional notice would amend labelling and electronic Instructions for Use (eIFU) requirements for Class II and Class III monitoring and therapeutic medical devices sold in the FADDR jurisdiction. It would (hypothetically):"),
        bullet("Require a machine-readable UDI symbol in a standardized position on primary packaging."),
        bullet("Require electronic Instructions for Use to be available, cached, in the user's selected language within companion software, not only via a web link."),
        bullet("Require cybersecurity labelling disclosures for any device with wireless connectivity, including supported update mechanisms."),
        bullet("Shorten the post-market safety reporting window for a newly-defined category of \"connected monitoring events.\""),

        h1("2. Numbered hypothetical requirements"),
        table(
          ["#", "Requirement", "Category"],
          [
            ["R1", "Primary packaging must carry a UDI symbol in the fictional \"Zone C\" position defined in this notice's (nonexistent) Annex B.", "Labelling"],
            ["R2", "Companion software must render the eIFU in the user's selected system language, cached for offline use.", "Labelling / Software"],
            ["R3", "Any device with wireless connectivity must disclose its supported firmware/software update mechanism.", "Cybersecurity"],
            ["R4", "\"Connected monitoring events\" must be reported to FADDR within 10 fictional business days, down from 30.", "Post-Market Surveillance"],
            ["R5", "Existing registrations for affected device classes must be updated with a labelling-compliance attestation.", "Registration"],
          ],
          [700, 6900, 2000]
        ),

        h1("3. Potential deficiencies and rationale"),
        table(
          ["#", "Potential deficiency", "Rationale"],
          [
            ["D1", "Primary packaging may not have a UDI symbol in the \"Zone C\" position.", "R1 defines a new placement rule not designed against existing artwork."],
            ["D2", "eIFU may be served only via an external link, not cached offline.", "R2 requires offline-renderable, language-selected eIFU."],
            ["D3", "Wireless device labelling may not disclose its update mechanism.", "R3 is a new disclosure not anticipated by prior labelling cycles."],
            ["D4", "Post-market reporting procedures may reference the old window.", "R4 shortens the window from 30 to 10 fictional days."],
            ["D5", "A registration record may lack the new compliance attestation.", "R5 requires an attestation not present in current fictional data."],
          ],
          [700, 4200, 4700]
        ),
        p("\"Potentially Affected\" and \"Requires Review\" are the only status labels used below. Nothing here, and nothing PARIVART generates from it, states that a product IS non-compliant — only that a human reviewer should check a specific, named gap.", { italics: true }),

        h1("4. Potentially affected demo products, markets, and processes"),
        p("Mapped against the Asterion Medical Systems demo portfolio (app/seeds/demo_data.py) for demonstration only:"),
        table(
          ["Demo product", "Potentially affected by", "Markets to review", "Processes to review"],
          [
            ["Asterion PulseSense (wearable, Class II)", "D1, D3", "US, EU, UK", "Labeling, Regulatory Submission"],
            ["Asterion CardioTrack (implantable, Class III)", "D1, D4", "US, EU", "Labeling, Post-Market Surveillance"],
            ["Asterion NeoMonitor (ICU monitoring, Class II)", "D2, D3", "US, Canada", "Labeling, Clinical Evaluation"],
            ["Asterion VitalHub (bedside monitor, Class II)", "D2, D4, D5", "EU, UK, India", "Labeling, Regulatory Submission, PMS"],
            ["Asterion InfuFlow (infusion pump, Class II)", "D5", "US, India", "Regulatory Submission"],
          ],
          [2600, 1600, 1800, 3600]
        ),

        h1("5. Evidence required to assess each potential deficiency"),
        table(
          ["Deficiency", "Evidence a reviewer would need"],
          [
            ["D1", "Current packaging artwork/specification showing UDI symbol placement."],
            ["D2", "Companion software screenshots or a build showing eIFU delivery (link vs. cached render)."],
            ["D3", "Current labelling text/artwork for wireless-connectivity disclosures."],
            ["D4", "The current post-market safety reporting SOP, showing the stated reporting window."],
            ["D5", "The current registration record for the product/market pair."],
          ],
          [1500, 8100]
        ),

        h1("6. Recommended human review steps"),
        new Paragraph({ numbering: { reference: "review-steps", level: 0 }, text: "A Regulatory Affairs reviewer confirms whether each \"Potentially Affected\" mapping above is accurate — PARIVART's deterministic matching only establishes a candidate link via product/market/process/jurisdiction overlap; it does not confirm actual non-compliance." }),
        new Paragraph({ numbering: { reference: "review-steps", level: 0 }, text: "For each confirmed candidate, the reviewer records an ImpactReview decision (ACCEPT, MODIFY, REJECT, or NEEDS_MORE_INFORMATION) against the generated impact assessment." }),
        new Paragraph({ numbering: { reference: "review-steps", level: 0 }, text: "Only on ACCEPT or MODIFY does a remediation Action get created, with the evidence in Section 5 attached as it is gathered." }),
        new Paragraph({ numbering: { reference: "review-steps", level: 0 }, text: "No Action is closed without the evidence listed in Section 5 being on file." }),

        h1("7. Suggested actions, owners, priorities, and due dates"),
        table(
          ["Action", "Suggested owner role", "Priority", "Suggested due date"],
          [
            ["Verify/update UDI symbol placement", "Regulatory Affairs Lead", "HIGH", "60 days before effective date"],
            ["Update companion software eIFU caching", "Software Engineering Lead", "HIGH", "90 days before effective date"],
            ["Add wireless update-mechanism disclosure", "Regulatory Affairs Lead", "MEDIUM", "60 days before effective date"],
            ["Update post-market reporting SOP", "Quality Manager", "MEDIUM", "30 days before effective date"],
            ["File registration compliance attestations", "Regulatory Affairs Lead", "HIGH", "30 days before effective date"],
          ],
          [3200, 2600, 1300, 2500]
        ),

        h1("8. Acceptance and closure criteria"),
        p("An action derived from this notice may be marked COMPLETED only when:"),
        bullet("The specific evidence listed in Section 5 for its deficiency is attached as Evidence on the action, AND"),
        bullet("A reviewer with appropriate authority has recorded an ImpactReview decision of ACCEPT on the governing impact assessment (or a later re-assessment superseding it), AND"),
        bullet("The AuditEvent trail for the action shows a complete OPEN -> IN_PROGRESS -> COMPLETED history with no unexplained status gaps."),
        p("An action should instead be left BLOCKED if evidence cannot yet be produced, with a note explaining the blocker — never marked COMPLETED on the assumption that it will be produced later."),

        h1("9. Traceability"),
        table(
          ["Requirement", "Deficiency", "Affected product(s)", "Suggested action", "Evidence required"],
          [
            ["R1", "D1", "PulseSense, CardioTrack", "Verify/update UDI placement", "Packaging artwork/spec"],
            ["R2", "D2", "NeoMonitor, VitalHub", "Update eIFU caching", "Software screenshots/build"],
            ["R3", "D3", "PulseSense, NeoMonitor", "Add wireless disclosure", "Current labelling text/artwork"],
            ["R4", "D4", "CardioTrack, VitalHub", "Update reporting SOP", "Current reporting SOP"],
            ["R5", "D5", "VitalHub, InfuFlow", "File registration attestations", "Current registration record"],
          ],
          [1400, 1300, 2100, 2300, 2500]
        ),

        banner("Reminder: this entire document — authority, identifier, dates, requirements, deficiencies, and portfolio mapping — is fictional and created only to demonstrate the PARIVART product. It must not be treated as a real regulatory instrument, legal advice, or evidence of an actual compliance gap."),
      ],
    },
  ],
  numbering: {
    config: [
      { reference: "review-steps", levels: [{ level: 0, format: "decimal", text: "%1.", alignment: AlignmentType.START }] },
    ],
  },
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("PARIVART_Demo_Regulatory_Notice.docx", buf);
  console.log("written");
});

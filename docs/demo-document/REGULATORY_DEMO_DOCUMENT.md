> **⚠ SYNTHETIC DEMONSTRATION DOCUMENT — NOT A REAL REGULATION ⚠**
> This document is entirely fictional. It was created solely to demonstrate the PARIVART
> Regulatory Change Intelligence product. The authority named below does not exist, the
> document identifier is invented, and the dates, requirements, and deficiencies are
> hypothetical. **This is not legal advice, not a real regulatory filing, and not evidence
> of any actual deficiency in any real product.** Do not act on its contents outside a
> product demonstration.

---

# Notice of Amendment — Labelling and Electronic Instructions for Use for Class II/III Monitoring and Therapeutic Devices

**Issuing Authority (fictional):** Federal Agency for Demonstrative Device Regulation ("FADDR") — a fictional body invented for this demonstration only, not affiliated with any real regulator.

**Document identifier (fictional):** FADDR-DEMO-2026-0147

**Publication date (fictional):** 2026-09-15
**Effective date (fictional):** 2027-01-01

---

## 1. Summary of the hypothetical regulatory change

This fictional notice would amend labelling and electronic Instructions for Use (eIFU)
requirements for Class II and Class III monitoring and therapeutic medical devices sold
in the FADDR jurisdiction. It would (hypothetically):

1. Require a machine-readable UDI (Unique Device Identifier) symbol in a standardized
   position on primary packaging.
2. Require that electronic Instructions for Use be available in the user's selected
   language within the device's companion software, not only via a web link.
3. Require cybersecurity labelling disclosures for any device with wireless
   connectivity, including a summary of supported update mechanisms.
4. Shorten the post-market safety reporting window for a newly-defined category of
   "connected monitoring events."

## 2. Numbered hypothetical requirements

| # | Requirement | Category |
|---|---|---|
| R1 | Primary packaging must carry a UDI symbol in the fictional "Zone C" position defined in this notice's (nonexistent) Annex B. | Labelling |
| R2 | Companion software must render the eIFU in the user's selected system language, cached for offline use, not solely a hyperlink to a hosted PDF. | Labelling / Software |
| R3 | Any device with wireless connectivity must disclose, in its labelling, a summary of its supported firmware/software update mechanism. | Cybersecurity |
| R4 | "Connected monitoring events" (a category this fictional notice defines) must be reported to FADDR within 10 fictional business days of discovery, down from the fictional prior 30-day window. | Post-Market Surveillance / Reporting |
| R5 | Existing registrations for affected device classes must be updated with a labelling-compliance attestation before the fictional effective date. | Registration |

## 3. Potential deficiencies and rationale

| # | Potential deficiency | Rationale |
|---|---|---|
| D1 | A device's primary packaging may not have a UDI symbol in the fictional "Zone C" position. | R1 defines a new placement rule; existing packaging artwork was not designed against it. |
| D2 | A device's eIFU may be served only via an external hyperlink rather than cached in companion software. | R2 requires offline-renderable, language-selected eIFU; a link-only implementation would not satisfy this hypothetical requirement. |
| D3 | A wirelessly-connected device's labelling may not disclose its update mechanism. | R3 is a new disclosure; prior labelling cycles would not have anticipated it. |
| D4 | Post-market reporting procedures may still reference the old reporting window. | R4 shortens the window; a procedure last updated before this fictional notice would be out of step with it. |
| D5 | A registration record may lack the new compliance attestation. | R5 requires an attestation that does not exist in current fictional registration data. |

**Potentially Affected** and **Requires Review** are the only status labels used below.
Nothing in this document, and nothing PARIVART generates from it, states that a product
*is* non-compliant — only that a human reviewer should check a specific, named gap.

## 4. Potentially affected demo products, markets, and processes

Mapped against the Asterion Medical Systems demo portfolio (see
`app/seeds/demo_data.py`) for demonstration purposes only:

| Demo product | Potentially affected by | Markets to review | Processes to review |
|---|---|---|---|
| Asterion PulseSense (wearable, Class II) | D1, D3 (wireless) | United States, European Union, United Kingdom | Labeling, Regulatory Submission |
| Asterion CardioTrack (implantable, Class III) | D1, D4 | United States, European Union | Labeling, Post-Market Surveillance |
| Asterion NeoMonitor (ICU monitoring, Class II) | D2, D3 | United States, Canada | Labeling, Clinical Evaluation |
| Asterion VitalHub (bedside monitor, Class II) | D2, D4, D5 | European Union, United Kingdom, India | Labeling, Regulatory Submission, Post-Market Surveillance |
| Asterion InfuFlow (infusion pump, Class II) | D5 | United States, India | Regulatory Submission |

## 5. Evidence required to assess each potential deficiency

| Deficiency | Evidence a reviewer would need |
|---|---|
| D1 | Current packaging artwork/specification showing UDI symbol placement. |
| D2 | Companion software screenshots or a build showing how the eIFU is currently delivered (link vs. cached render). |
| D3 | Current labelling text/artwork for wireless-connectivity disclosures. |
| D4 | The current post-market safety reporting SOP, showing the stated reporting window. |
| D5 | The current registration record for the product/market pair, showing whether an attestation field exists or is populated. |

## 6. Recommended human review steps

1. A Regulatory Affairs reviewer confirms whether each "Potentially Affected" mapping
   above is accurate for the named product/market pair — PARIVART's deterministic
   matching only establishes a candidate link via product/market/process/jurisdiction
   overlap; it does not confirm actual non-compliance.
2. For each confirmed candidate, the reviewer records an `ImpactReview` decision
   (`ACCEPT`, `MODIFY`, `REJECT`, or `NEEDS_MORE_INFORMATION`) against the generated
   impact assessment.
3. Only on `ACCEPT` or `MODIFY` does a remediation `Action` get created, with the
   evidence in Section 5 attached as it is gathered.
4. No `Action` is closed without the evidence listed in Section 5 being on file.

## 7. Suggested actions, owners, priorities, and due dates

| Action | Suggested owner role | Priority | Suggested due date (relative to effective date) |
|---|---|---|---|
| Verify/update UDI symbol placement on affected packaging | Regulatory Affairs Lead | HIGH | 60 days before effective date |
| Update companion software to cache eIFU offline, per selected language | Software Engineering Lead | HIGH | 90 days before effective date |
| Add wireless update-mechanism disclosure to labelling | Regulatory Affairs Lead | MEDIUM | 60 days before effective date |
| Update post-market reporting SOP to the new window | Quality Manager | MEDIUM | 30 days before effective date |
| File registration compliance attestations | Regulatory Affairs Lead | HIGH | 30 days before effective date |

## 8. Acceptance and closure criteria

An action derived from this notice may be marked `COMPLETED` only when:

- The specific evidence listed in Section 5 for its deficiency is attached as `Evidence`
  on the action, **and**
- A reviewer with appropriate authority has recorded an `ImpactReview` decision of
  `ACCEPT` on the governing impact assessment (or a later re-assessment superseding it),
  **and**
- The `AuditEvent` trail for the action shows a complete `OPEN → IN_PROGRESS →
  COMPLETED` history with no unexplained status gaps.

An action should instead be left `BLOCKED` if evidence cannot yet be produced, with a
note explaining the blocker — never marked `COMPLETED` on the assumption that it will be
produced later.

## 9. Traceability

| Requirement | Potential deficiency | Affected product(s) | Suggested action | Evidence required |
|---|---|---|---|---|
| R1 | D1 | PulseSense, CardioTrack | Verify/update UDI symbol placement | Packaging artwork/spec |
| R2 | D2 | NeoMonitor, VitalHub | Update companion software eIFU caching | Software screenshots/build |
| R3 | D3 | PulseSense, NeoMonitor | Add wireless disclosure to labelling | Current labelling text/artwork |
| R4 | D4 | CardioTrack, VitalHub | Update post-market reporting SOP | Current reporting SOP |
| R5 | D5 | VitalHub, InfuFlow | File registration attestations | Current registration record |

---

> **Reminder: this entire document, including the authority, identifier, dates,
> requirements, deficiencies, and portfolio mapping, is fictional and created only to
> demonstrate the PARIVART product. It must not be treated as a real regulatory
> instrument, legal advice, or evidence of an actual compliance gap.**

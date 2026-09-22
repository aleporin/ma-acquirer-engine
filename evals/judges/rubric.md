# Labeling guide

Read each page alongside its target and supplied evidence before seeing judge
output. Enter one of `Pass`, `Fail`, or `Unknown` in each of its five CSV columns.
`Unknown` means the supplied material is insufficient to decide, not that the
writing is mediocre. A clear failure should be marked `Fail`.

| Column | Pass when… | Fail when… |
| --- | --- | --- |
| specificity | The rationale explains this buyer using its particular history or capabilities. | The text could fit most candidates after replacing the name. |
| thesis_evidence_link | The acquisition thesis follows from relevant supplied evidence and separates facts from inference. | A central thesis is unsupported or contradicts the evidence. |
| risk_relevance | Risks address this buyer, target, or transaction with a defensible evidence basis. | Risks are boilerplate, misleading, or irrelevant to the proposed deal. |
| conviction_defensibility | The stated conviction matches the strength and limits of the evidence. | Confidence is overstated, inconsistent, or justified with unsupported claims. |
| banker_tone | The page is concise, specific, sober, and suitable for a professional advisory discussion. | It relies on hype, vague filler, or unwarranted certainty. |

Judge the visible page, not hidden implementation details. Honest Medium
conviction may pass for every buyer; varied labels are not a quality requirement.
The evidence section is reference material, not prose whose style you must grade.
Do not infer a missing fact from outside knowledge.

The packet hides generation run, prompt, reviewer setting, and judge results.
Buyer names remain visible for assessing the business argument. Complete all
rows before requesting judge output; the runner rejects blanks and unknown IDs.

| Clip | Description | Endpoint | Expected Tier | Suggested Tier | Tier Match | Field Accuracy | Latency |
|------|-------------|----------|---------------|----------------|------------|----------------|---------|
| clip01 | Chest pain with hypotensive vitals | /triage | critical | critical | ✓ | 100% | 2.9 s |
| clip01-kn | Chest pain with hypotensive vitals (Kannada-English mixed) | /triage | critical | critical | ✓ | 100% | 3.2 s |
| clip02 | Unconscious patient | /triage | critical | critical | ✓ | 86% | 2.8 s |
| clip03 | Stroke with classic signs | /triage | critical | stable | ✗ | 86% | 2.8 s |
| clip04 | Pediatric fracture | /triage | urgent | urgent | ✓ | 86% | 2.9 s |
| clip05 | Respiratory distress with low SpO2 | /triage | critical | critical | ✓ | 100% | 2.8 s |
| clip05-kn | Respiratory distress with low SpO2 (Kannada-English mixed) | /triage | critical | critical | ✓ | 86% | 2.8 s |
| clip06 | Significant burn injury | /triage | critical | stable | ✗ | 86% | 2.8 s |
| clip07 | Controlled moderate bleeding | /triage | urgent | stable | ✗ | 86% | 2.8 s |
| clip08 | Minor injury with normal vitals | /triage | stable | stable | ✓ | 57% | 2.9 s |
| clip09 | Fire dispatch with trapped person | /triage | fire_with_trapped | fire_with_trapped | ✓ | 86% | 2.8 s |
| clip10 | Intervention log entry (for /log endpoint, not /triage) | /log | - | - | - | interventions ✓ | 2.8 s |

| Field | Accuracy |
|-------|----------|
| age | 100% |
| sex | 100% |
| complaint | 36% |
| conscious | 91% |
| breathing | 82% |
| vitals | 100% |
| trapped_persons | 100% |

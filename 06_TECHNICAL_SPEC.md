*Last updated: 2026-03-31 — Deed [318] added to Deed Register — Warranty Deed w/ Vendor's Lien, Ennis + Dorsett + JP Black → Simmons; Boyd Survey DISPOSED; ISSUE-01 RESOLVED*
# Black Land Project — Technical Project Specification


---

## Project Purpose

Build a web application that:
1. Maps the family's Texas land holdings as georeferenced polygons derived from metes-and-bounds deed descriptions
2. Tracks the deed chain for each parcel through a database of conveyances
3. Tracks mineral interest ownership by tract, including splits, severances, and fractions
4. Provides a mobile-friendly courthouse research workflow (offline capable)
5. Generates flags and alerts for title defects and data inconsistencies

---

## Architecture Decisions

### Deployment
- **Platform**: Google Cloud Run (serverless; scales to zero)
- **Prior cost optimization**: Reduced from $45/month to $0.50/month via cleanup policies and storage management
- **Database**: PostgreSQL with PostGIS extension (for geometry storage and spatial queries)
- **Frontend**: Mobile-first web app (React or similar); must work offline at courthouse

### GIS Stack
- **Polygon computation**: Metes-and-bounds descriptions → GeoJSON polygons
  - Input unit: Texas varas (1 vara ≈ 33.33 inches)
  - Reference datum: NAD83 or WGS84
  - Bearing format: Degrees-minutes with compass quadrant (e.g., N55°00'E)
  - Closure check: Every polygon must close; flag if it doesn't
- **Base map / reference parcels**: County CAD parcel shapefiles
  - Limestone County: Acquire from Limestone CAD or Texas comptroller GIS
  - Freestone County: Acquire from Freestone CAD or Texas comptroller GIS
- **Visualization**: Display computed polygon overlaid on CAD parcel; side-by-side or overlay comparison
- **Flag**: CAD parcel ≠ deed polygon (acreage difference > X%) — flag for review

### Data Sources
- Texas GLO original patents: https://s3.amazonaws.com/tnris-mailing-cdn/Texas-GLO-Scanned-Maps...
- Texas Comptroller parcel data: https://comptroller.texas.gov/taxes/property-tax/
- Limestone County CAD: limestone-cad.org (or similar)
- Freestone County CAD: freestonecad.org (or similar)

---

## Database Schema (Core Tables)

### `parcels`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| cad_id | varchar | e.g., L20554; may be null for historic-only tracts |
| county | enum | limestone, freestone |
| survey_name | varchar | e.g., "Sarah McAnulty Survey A-19" |
| acreage_deed | decimal | As stated in deed |
| acreage_cad | decimal | From CAD shapefile |
| acreage_computed | decimal | From polygon computation |
| current_owner | FK → entities | |
| geometry | geometry(Polygon, 4326) | PostGIS |
| notes | text | |

### `deeds`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| phase | varchar | Phase 1 through Phase 7 |
| filename | varchar | Canonical filename from naming convention |
| instrument_date | date | |
| recording_date | date | |
| instrument_type | enum | warranty, special_warranty, quitclaim, gift, partition, distribution, trustmemo |
| grantor | FK → entities | |
| grantee | FK → entities | |
| county | enum | |
| volume_page | varchar | e.g., "Vol 12 Pg 456" or instrument number |
| interest_type | enum | surface, minerals, surface+minerals, royalty, trust, estate |
| acreage_stated | decimal | |
| consideration | varchar | |
| has_mineral_reservation | boolean | |
| mineral_reservation_text | text | Verbatim reservation language if present |
| document_url | varchar | GCS URL to deed PDF/image |
| notes | text | |
| flags | text[] | e.g., ["acreage_discrepancy", "missing_prior_deed"] |

### `parcel_deed_map` (many-to-many)
| Field | Type | Notes |
|---|---|---|
| parcel_id | FK → parcels | |
| deed_id | FK → deeds | |
| role | enum | created_by, conveys, carves_from, references | |
| notes | text | |

### `mineral_interests`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| parcel_id | FK → parcels | |
| interest_type | enum | mineral_estate, royalty, npri, working_interest, executive_rights |
| fraction_numerator | int | |
| fraction_denominator | int | |
| owner | FK → entities | |
| source_deed_id | FK → deeds | |
| notes | text | |

### `entities`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | varchar | |
| entity_type | enum | individual, trust, llc, estate, church, railroad, utility |
| status | enum | active, deceased, dissolved, unknown |
| notes | text | |

### `research_queue`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| description | text | What to find |
| priority | enum | high, medium, low |
| related_parcel | FK → parcels | |
| related_deed | FK → deeds | |
| county | enum | |
| search_type | enum | deed, probate, mineral_lease, heirship, plat, other |
| assigned_to | varchar | |
| status | enum | open, in_progress, resolved |
| resolution_notes | text | |

### `issues` (title defects and flags)
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| issue_code | varchar | e.g., ISSUE-01 |
| title | varchar | Short description |
| risk_level | enum | high, medium, low |
| related_parcel | FK → parcels | |
| description | text | Full analysis |
| action_required | text | |
| status | enum | open, in_progress, resolved |
| resolution_notes | text | |

---

## Deed Description Parsing

### Input Format (from canonical filenames)
```
[DATE]_[SEQ]_[COUNTY]_[INSTRUMENT]_[INTEREST]_[GRANTOR]_[GRANTEE].txt
```
- Date: YYYY-MM-DD
- Seq: [##] sequential number within phase
- County: f (Freestone) or l (Limestone)

### Call Parsing
Metes-and-bounds calls format:
```
THENCE [bearing] [distance] [unit] [monument/corner]
```
- Bearings: N/S [degrees]°[minutes]' [E/W] — store as decimal degrees
- Distance units: varas or vrs (convert to feet: 1 vara = 33.33 in ≈ 2.778 ft)
- Monument types: stake, rock, P.O. (post oak), other tree species, county line, railroad ROW, creek meanders

### Monument Resolution
Creek/river meanders: "with meanders of said ravine" → interpolate or mark as approximation
Neighbor references: "SW corner of Tom Bounds 114-acre tract" → requires pulling neighbor's chain
Railroad ROW: H&TC RR = Houston & Texas Central → now Union Pacific; ROW is documentable

### Known Bearing Issues
**N32 ambiguity — RESOLVED**
- Original concern: Deed [22] (1906 source) shows N32°W as first ravine call; later deeds show S32°W
- Resolution: PDFs confirmed for [05], [23], [28] — all show S32°W. The [112] source text for deed [22] reads "N. 32 W 32 vrs" — confirming the N32 reading in the 1906 original. This is the originating scrivener's error; all post-1972 deeds corrected to S32°W. Deed [01] (1923) also uses S32°W. The 1906 deed is the sole instrument with N32.

**N78 systematic error — DISCOVERED DURING PHASE 3 PDF VALIDATION**
- Error pattern: The 7th ravine meandering call (S78°W 50 vrs.) was transcribed as N78°W in the original phase files
- Confirmed by PDFs for deeds [05], [23], [27], [28] — all show S78°W
- **Corrected in**: PHASE_3.txt for deeds [05], [23], [27], [28], [29], [30]
- **Flagged as pending validation** in PHASE_1.txt for deed [01] (1923 source deed not yet PDF-reviewed for bearing calls). **Deed [22] now validated**: the [112] source text reads "N 78 W 50 vrs" — confirming the N78 reading in the 1906 original (vs. S78°W in all post-1972 deeds). The originating N78 error is in the 1906 deed; downstream corrections to S78 are correct.
- Note: Deed [22] recording data now confirmed from [112] source text: filed April 13, 1910 at 1 PM; recorded April 14, 1910 at 3 PM; O.C. Frazier, Clerk County Court, Limestone County; A. H. Sandell, Deputy. ⚠️ Prior entry referenced "V.E. Brogden" as clerk from a separate PDF examination — discrepancy flagged; see PHASE_1.txt deed [22] notes. Year "1910" squeezed into stamp confirmed by personal PDF examination; consistent with [112] source text.
- GIS impact: A polygon computed with N78°W instead of S78°W would place the ravine meander ~100 varas (~277 ft) in the wrong direction — significant polygon error

**Deed [24] bearing corrections — DISCOVERED DURING PHASE 2 PDF VALIDATION**
- Error pattern: Three bearing calls in Second Tract of Deed [24] (1974-12-30, Limestone) were incorrect in prior transcription
- Confirmed by PDF:
  - First bearing of Second Tract: corrected from S80°30'E to **S88°30'00"E**
  - Second bearing of Second Tract: corrected from S40°E to **S04°00'00"E**
  - Third bearing of Second Tract: corrected from N86°30'W to **N88°30'00"W**
- **Corrected in**: PHASE_2.txt (current version)
- GIS impact: The S40°E → S04°00'00"E correction in particular represents a 36-degree bearing shift — would produce a significantly incorrect polygon if not corrected. The S80°30'E → S88°30'00"E and N86°30'W → N88°30'00"W corrections are ~8-degree shifts, also material.

**Deed [24] measurement note**
- Third Tract beginning distance: "131-1/8 ft" — exact fraction confirmed by PDF. Decimal equivalent is 131.125 ft. Any transcription or computation using 131.13 ft introduces a 0.005 ft rounding error. Use 131.125 ft or the exact fraction for surveying computations.

**Exhibit A Sixth Tract — "S. Slaughter" Survey Name Error (PDF-confirmed, Phase 5A)**
- Error: Exhibit A Sixth Tract in deeds [14] and [17] (and likely all deeds using this Exhibit A template) reads "S. Slaughter Survey A-565." Correct name: **B. Slaughter (Benjamin Slaughter) Survey A-565.**
- Scope: Every deed containing this Exhibit A carries the error — it was in the original template from which each deed was prepared.
- All other Exhibit A tracts in the same survey correctly use "B. Slaughter." CAD uses "B. Slaughter."
- GIS impact: None — A-565 is unambiguous. Database should use "B. Slaughter A-565" for the parcels table regardless of deed text.
- See ISSUE-27.

**Deed [17] Exhibit C — Blank Page Number (PDF-confirmed, Phase 5A)**
- "Volume 35, Page _" — underlined blank in original instrument for Mayo→Beene/Ausley 1907 deed. Page number never filled in by preparing attorney.
- The Edwards Tract is sufficiently identified by the Beene→Edwards 1911 reference (Vol 47 p.501) and the full metes-and-bounds description.
- See ISSUE-28.

**Deed [22]/[112] Second Tract — Manning Recording Citation "Book S" Scrivener's Error (Integration Session 1)**
- Deed [22] source text (= deed [112]) reads "Book S page 661" for the Reuben Manning→JH Bounds deed (July 20, 1869). The correct citation is **Book G, page 661**.
- Confirmed by: Deed [116] (1937, Third Tract) independently cites the identical Reuben Manning→JH Bounds deed as "Book G. page 661." Deed [01] (1923, Second Tract) also uses "vol G, page 661." The 2005 deeds reference "Book G page 661."
- "Book S" in deed [22]/[112] is an isolated scrivener's error in the 1906 original instrument. All downstream citations use Book G.
- Annotated [sic] in PHASE_1.txt deed [22] entry.
- See ISSUE-15.

**Exhibit A First Tract — "C.C. Bollard" Spelling — RESOLVED (PDF-confirmed by landowner, 2026-03-08)**
- Deed [14] and [17] Exhibit A First Tract were misread by AI transcription as "C.C. **Bollard** et ux." The 1908 source deed (Vol. 31 p.182, Freestone County) was PDF-verified directly by the landowner: the correct spelling is **"C.C. Ballard et ux."** The straight downstroke of the handwritten "a" was misread as "o" by OCR/AI. "Bollard" never appeared in any recorded instrument — the public record has always said "Ballard." Freestone County deed index confirms 495 records under "Ballard," zero under "Bollard." All tracking file references now use "Ballard." No curative action required.

---

## Survey Abstract Number History — Sarah McAnulty Survey

The Sarah McAnulty Survey originates as a single original Mexican land grant, subsequently administered by the Republic of Texas and then the State of Texas. When the state assigned abstract numbers to surveys, the McAnulty survey was designated **A-19**. At the time of assignment, A-19 covered land in what would become both Limestone and Freestone Counties.

As county boundaries were established and formalized, portions of the survey fell on each side of the Limestone/Freestone county line. At some point — likely after significant settlement had occurred in both counties — the Texas General Land Office (or county surveyors) assigned the abstract number **A-751** to the Freestone County portion of the survey, while retaining **A-19** for the Limestone County portion.

**Current designations:**
- **Sarah McAnulty Survey A-19** = Limestone County portion
- **Sarah McAnulty Survey A-751** = Freestone County portion

**Practical consequence for deed research:**
Deeds drafted before or during the A-751 assignment transition may use "Sarah McAnulty Survey, A-19, Freestone County" for land that is physically in Limestone County — reflecting the undivided original designation when attorneys, surveyors, and fieldnote preparers had not yet internalized the split. This causes apparent county designation conflicts in the deed records that are historical artifacts, not title defects.

**Affected instruments in this file set:**
- Deeds **[10], [11], [31], [32]** (1992–1993): all describe parcel L20552 as "Sarah McAnulty Survey, A-19, Freestone County, Texas." The parcel is physically in Limestone County and correctly classified as Limestone County (A-19) in CAD. Phase transcriptions annotated with survey history note at first occurrence in each deed.
- Deed **[35]** (2005): uses "Sarah McAnulty Survey, A-17" throughout — separate scrivener's error (wrong abstract number entirely; correct number is A-19 for Limestone County; see ISSUE-20). Annotated [sic] throughout PHASE_3.txt.
- Deed **[34]** (2005): uses "Sarah McAnulty Survey, A-17" in deed body property description and in Exhibit A — same scrivener's error as deed [35]; same attorney (Geneva Brown Turner), same date (July 7, 2005). Annotated [sic] at both occurrences in PHASE_7.txt. See ISSUE-20.

**GIS / database implication:**
When building the parcels table, use the correct current designation (A-19 for Limestone, A-751 for Freestone) regardless of what the source deed says. Flag deeds that contain "A-19, Freestone County" with a `survey_designation_historical` flag and cross-reference this note.

---

## Courthouse Workflow (Mobile App Features)

### Required for offline use
- Service worker or local-first architecture (sync when connected)
- Pre-loaded list of known deeds and parcels for reference
- Offline queue for new deed logging

### Fast logging at courthouse
1. Scan/photo of deed → upload to GCS
2. Quick entry form: grantor, grantee, instrument date, instrument number, county, book/volume/page
3. Auto-detect interest type from filename convention
4. Flag as "pending full processing" — don't block research workflow

### Research queue at courthouse
- Tap any open research queue item → opens county + search type + description
- Log what was found, upload images
- Mark resolved or escalate

---

## Flagging Rules (Automatic)

| Trigger | Flag |
|---|---|
| Deed acreage ≠ CAD acreage (>5% difference) | `acreage_discrepancy` |
| Mineral interests for a parcel don't sum to 1 (whole) | `mineral_fraction_gap` |
| Deed references an instrument not in the database | `missing_prior_deed` |
| Polygon doesn't close (computation fails) | `polygon_closure_fail` |
| Bearing ambiguity detected (conflicting calls) | `bearing_conflict` |
| Mineral reservation present | `mineral_severance` |
| Reversion clause present | `reversion_clause` |
| No title insurance on record | `no_title_insurance` |
| Grantee in a prior deed not in any subsequent deed as grantor (end of chain) | `chain_gap` |

---

## Phased Development Plan

### Phase A — Foundation (current priority)
- Database schema and Cloud Run deployment
- Seed all analyzed deed data (Phases 1-7)
- Parcel table with known CAD IDs
- Issues table pre-populated from this document
- Research queue pre-populated with known open searches

### Phase B — GIS
- Polygon computation from metes-and-bounds calls
- PostGIS storage and spatial queries
- Map UI with CAD parcel overlay
- Flag polygon vs. CAD discrepancies

### Phase C — Courthouse App
- Offline-capable mobile UI
- Fast deed logging form
- Research queue management

### Phase D — Mineral Rights Tracker
- Mineral interest table with fraction arithmetic
- Cross-parcel mineral ownership views
- Lease detection (if oil and gas leases are pulled from courthouse records)

---

---

## Probate and Court Records — FC Index Confirmed

The following records were identified in the Freestone County complete deed index (JSON export, 2026-03-08). Since the JSON files represent ALL Freestone County recorded documents (not just deeds), presence in this index confirms these instruments exist in the county records. Absence from the index means the instrument does not exist in Freestone County records.

| Instrument | County | Citation | Recorded | Description | PDF |
|---|---|---|---|---|---|
| MS Bounds Estate Probate | Freestone | OR/949/605, Doc# 1995-380 | 01/24/1995 | Probate of M.S. Bounds (d. 1977) — filed in FC 18 years after death, timed to support the 1995 NationsBank→Beard trustee substitution (deed [12]). May contain estate inventory documenting how the Vickers 1/16 royalty (ISSUE-07) passed to subsequent holders. | ⬜ |
| Mattie Mae Bounds Estate Probate | Freestone | OR/949/611, Doc# 1995-381 | 01/24/1995 | Probate of Mattie Mae Bounds (d. 1970) — filed in FC 25 years after death, same date as MS Bounds probate. Same NationsBank→Beard closing purpose. | ⬜ |
| Olena Bounds Black Estate Affidavit | Freestone | OR/1327/552, Doc# 2005-5004967 | 07/18/2005 | Affidavit re: Estate of Olena Bounds Black — filed same day as all 2005 distribution deeds (OR Vol. 1327 coordinated closing). Likely affidavit of heirship or death certificate preceding the July 2005 distribution. | ⬜ |
| Olena Bounds Black Estate Probate | Freestone | OR/1330/777, Doc# 2005-5005632 | 08/12/2005 | Full probate of Olena Bounds Black estate — filed approximately 3 weeks after the July 18 distribution closing. May contain estate inventory identifying the land inherited from **Lou Barry Bounds Martin** (Olena's maternal aunt, now identified — see ISSUE-16 and 01_FAMILY_ENTITY_STRUCTURE.md), and any instruments documenting how that land passed to Olena. | ⬜ |




**Edwards Source Deed Grantor Identification** [INDEX CONFIRMED: FC, 2026-03-09]
FC Doc# 1943-1482, DR Vol. 168, Pg. 588 — confirmed by FC index. Document type: WARRANTY DEED. Grantee: BLACK J P. Recorded date: 11/5/1943. Legal description: S MCANULTY SUR. **Two grantor entries in FC index**: (1) "EDWARDS JOHN W" (identified in prior session's index search); (2) "EDWARDS A H MRS" (identified in Edwards surname search, 2026-03-09). The FC public search maintains separate party entries per instrument — both names are grantors on the same document. This is consistent with the tracking file reference "Mrs. A.H. Edwards et al." — the "et al." includes John W. Edwards (likely husband and wife joining in conveyance of homestead property; see 1935 homestead affidavit below). **HUMAN VERIFICATION RECOMMENDED** (downgraded from REQUIRED) — PDF should confirm full grantor list and whether the deed conveys 85.30 acres specifically. The grantor name discrepancy is partially resolved.

**Edwards Homestead Affidavit (1935)** [INDEX IDENTIFIED: FC, 2026-03-09]
FC Doc# 1935-1333, DR Vol. 140, Pg. 502 — HOMESTEAD AFFIDAVIT/DECLARATION/DESIGNATION. Grantor: EDWARDS A H MRS. Grantee: PUBLIC. Recorded: 8/15/1935. Legal description: S MC ANULTY SUR. Mrs. A.H. Edwards designated the McAnulty Survey land as her homestead in 1935, eight years before conveying to JP Black (1943). Confirms continuous Edwards occupation; supports the chain from 1911 Beene→Edwards acquisition through the 1943 Edwards→Black conveyance. Chain support document — does not convey title. ⬜
## Source Document Authority & PDF Originals

### PDF Originals
PDF originals exist for all deeds in the project. These are the authoritative source documents. The text files (PHASE 1.txt through PHASE 7.txt) are working transcriptions only and must NOT be treated as authoritative for recording citations, dates, or exact legal descriptions.

**Known transcription error**: Deed [01] (Bessie Plunkett et al → MS Bounds) — text file states Bessie Plunkett's acknowledgment as December 1, 1923. PDF original confirms the correct date is **December 1, 1953** — a 30-year gap, not 4 years as the text implied. This error was caught by comparing the text against the PDF.

**Boilerplate form variation — 1979-1980 gift deeds**: Deeds [27], [28], [29], [30] were drafted by at least two different attorneys using different form books. Do NOT assume boilerplate is consistent across these four deeds. Confirmed differences include:
- Defined terms ("Grantor"/"Grantee"): present in [28]/[29]/[30], absent from [27]
- Warranty clause language: **[27], [28], [30]** use "thereto **in** anywise belonging" (corrected from prior grouping — [27] was PDF-corrected FROM "thereto and anywise" TO "thereto in anywise belonging," matching the original deed text; [29] retains "thereto **and** anywise")
- "any/of any part thereof": [27]/[29]/[30] use "of any part thereof"; [28] uses "or any part thereof"
- Warranty verb: [28]/[29] use "whomsoever"; [30] uses "whatsoever"
- 18/92 cumulative interest paragraph: present in [30] (genuine); absent from [28] (not fabricated — simply not included)

**Acknowledgment county vs. notary county inconsistency**: Deeds [29] and [30] both show COUNTY OF FREESTONE in the acknowledgment header but the notary's printed county is Limestone County. This is an internal inconsistency in the originals, not a transcription error. Do not "correct" either document.

**Protocol**: When a PDF is reviewed and confirms or corrects the text, note it in this table. For all critical details (recording citations, exact acreages, dates, reservation language), verify against the PDF before relying on the text.

### Confirmed Recording Citations (from PDF review)


**PDF Status Key**: ✓ = PDF in possession | ⬜ = Pull needed (citation known) | IDX = Index-identified only (citation from county index; pull needed)

| Deed | Grantor → Grantee | County | PDF | Record / Instrument | Pages | Filed | Recorded | Clerk |
|---|---|---|---|---|---|---|---|---|
| [101] | J. H. Bounds and wife M. E. Bounds → Mary M. Kindley [sic] / Lindley [sic] | Limestone | ✓ | Book "M" pp. 390–392 (confirmed from deed [105] cross-reference) | 390–392 | Jul 28, 1881 | Jul 28, 1881 | S. D. Walker, co. clk. / R. Wiley, Deputy; 99 ac, Samuel Holloway Survey; $1.00 (gift); Ack. before A. Barry, Limestone County, March 22, 1878; M. E. Bounds privy examination; warranty/gift deed, surface+minerals, no reservations; ⚠️ Vol/Pg confirmed from [105] cross-reference only — not direct notation; pull from Limestone County deed records to verify; ⚠️ name discrepancy in original: granting clause "Kindley" [sic], habendum "Lindley" [sic] — same person |
| [105] | J. P. Lindley and wife Mary M. Lindley → J. H. Bounds | Limestone | ✓ | Vol. 2, Pg. 383 [INDEX CONFIRMED: LC Vol.2 Pg.383, Inst# DR-00002-00383, 2026-03-09] | 383 | Dec 12, 1887 | Dec 17, 1887 | W. F. Brown, Co. Clk. / H. Williams, Dept., Limestone County; 69 ac, Samuel Holloway Survey, "S.E. & North portion"; $550 cash; Ack. before W. Allegra J.P. & Ex officio NP, Freestone County, May 29, 1886; Mary M. Lindley privy examination; warranty deed, surface+minerals, no reservations; cross-references [101] as "Books 'M' pages 390, 391 & 392"; ⚠️ triage catalog only for execution date — confirm against original at Vol. 2 Pg. 383 |
| [109] | J. H. Bounds and wife M. E. Bounds → R. E. Lee | Limestone | ✓ | [Page 514] per margin note; volume not stated | 514 | Mar 27, 1890 at 9 AM | Mar 26, 1890 at 3 PM | W. F. Brown, co. clk. / J. D. Brown, Dept., Limestone County; 69 ac, Samuel Holloway Survey; $690 via 4 VL notes; Ack. before J. E. Longbotham NP, Freestone County, Oct. 16, 1889; warranty with vendor's lien, surface+minerals, no reservations; ⚠️ RECORDING DATE PRECEDES FILING DATE — "recorded March 26, 1890" before "filed March 27, 1890" — clerk error in original (see ISSUE-39); cross-references [101] as "Books 'M' pages 390, 391 and 392" |
| [125] | J. P. Lindley + → R. E. Lee (Robert E. Lee) | Limestone | IDX | Vol. 8, Pg. 512 [INDEX IDENTIFIED: LC Vol.8 Pg.512, Inst# DR-00008-00512, 2026-03-09] | 512 | — | 03/22/1890 | 30 ac, Samuel Holloway Survey; Lindley J P + → Lee Robert E per LC index; disposition of Mary M. Lindley's 30-ac Holloway remainder; completes Holloway Survey chain — R.E. Lee held entire 99 ac by March 1890; execution date unknown; consideration unknown; ⚠️ INDEX-ONLY — pull from LC Vol. 8 Pg. 512 to confirm full details |
| [111] | J. H. Bounds and heirs at law → Webster Dean | Limestone | ✓ | Vol. 51, Pg. 537 [INDEX CONFIRMED: LC Vol.51 Pg.537, 2026-03-08] | — | Dec 7, 1906 at 9 AM | Dec 18, 1906 at 4 PM | W. C. Frazier, County Clerk / A. R. Henderson, Deputy, Limestone County; 107.25 ac (= 109 ac less 1¾ ac Tehuacana Valley Church tract), Sarah McAnulty Survey; $2,149.09 ($500 cash + three VL notes of $549.83 each at 8%, due Jan 1 1908/1909/1910); vendor's lien retained; warranty deed, surface+minerals, no reservations; ⚠️ triage catalog only for execution date; ⚠️ volume/page not in source text — pull from Limestone County deed records; large grantor group (23 individuals including M.M. Lindley feme sole and R.E. Lee Jon defs. Survivors Com.); companion instrument to deed [22] in 1906 McAnulty partition; parcel NOT in current inventory |
| [102] | J. W. Mallard → J. H. Bounds | Limestone | ✓ | Book O, Pg. 554 [INDEX CONFIRMED: LC Book O Pg.554, Inst# DR-0000O-00554, 2026-03-09] | 554 | Apr 8, 1882 at 5 PM | Apr 10, 1882 at 6 PM | S. D. Walker, co. clk. / R. Wiley, Deputy; 9 acres, Sarah McAnulty League; $30 cash; Notary: N. L. Waller, Limestone County; acknowledged Nov 21, 1881; warranty deed, surface+minerals, no reservations; NOTE: adjacent page to deed [103] (Pg. 553) in Book O — coordinated filing confirmed |
| [103] | J. O. Longbotham (wife M. J. Longbotham) → J. H. Bounds | Limestone | ✓ | Book O, Pg. 553 [INDEX CONFIRMED: LC Book O Pg.553, Inst# DR-0000O-00553, 2026-03-09] | 553 | Apr 8, 1882 at 5 PM | Apr 10, 1882 at 3 PM | S. D. Walker, Co. Clk. / R. Wiley, Deputy; 7.5 acres, McAnulty League; $75.50 cash; Acknowledged Freestone County before Warren Allegra JP & Ex off. NP, Dec 6, 1881 (grantor) and Dec 24, 1881 (wife M. J. Longbotham, privy exam); conveyance, surface+minerals, no reservations; NOTE: Pg. 553, adjacent to deed [102] at Pg. 554 — coordinated filing confirmed in Book O |
| [107] | JH Bounds & wife ME Bounds → Trustees of Colored New Home Baptist Church | Limestone | ✓ | ⚠️ PROBABLE: LC Vol. 32, Pg. 62 (per LC index Inst# DR-00032-00062, BOUNDS J H + → BROWN J M TRUSTEE +, S MC ANULTY HRS, 2 ACRES; **DATE DISCREPANCY**: index shows recorded 11/22/1897 vs. tracking file 11/28/1887 — 10-year gap requires human verification against original instrument) [INDEX PROBABLE: LC Vol.32 Pg.62, 2026-03-08]. Filed Nov 27, 1887; recorded Nov 28, 1887; W. F. Brown, Clerk County Court; Deputy A. J. S[ILLEGIBLE] | Volume/page pending confirmation | Nov 27, 1887 at 7 PM | Nov 28, 1887 at 3 PM | W. F. Brown, Clerk County Court, LC; 2-acre church parcel, Sarah McAnulty Survey; $32 consideration; condition on use ("Church, School and Grave yard purpose"); scrivener's errors: "Boyd County" (= Limestone County), "M. C. Bounds" (= M. E. Bounds); see ISSUE-09 (PERMANENTLY CLOSED) |
| [110] | A. M. Smith and wife Mary Smith (née Bennett) → J. H. Bounds | Limestone | ✓ | Book 8, Pg. 595 [INDEX CONFIRMED: LC Book 8 Pg.595, Inst# DR-00008-00595, 2026-03-09] | 595 | May 24, 1890 at 5 PM | May 26, 1890 at 9 AM | W. F. Brown, co clerk / H. Williams, Dept.; 9⅛ acres, Sarah McAnulty Headright Survey; $91.57 cash; Acknowledged before J. E. Longbotham NP, Freestone County, Feb 1, 1890; warranty deed, surface+minerals, no reservations; ⚠️ NOTARY CAPTION ERROR: Smith's acknowledgment caption reads "Limestone Co. Tex." but J. E. Longbotham is a Freestone County notary throughout; ⚠️ ACREAGE DISCREPANCY in deed body: "nine and one eighth acre" in granting clause vs. "9¼ acres" later — 9⅛ is correct per mathematical 1/8 of 73 acres |
| [22] | JH Bounds and adult children → MS Bounds | Limestone | ✓ | Book 63, Pg. 71–78 (per prior PDF examination and [16]/[37] cross-reference; not stated in [112] source text margin note) | 71–78 | Apr 13, 1910 at 1 PM | Apr 14, 1910 at 3 PM | O.C. Frazier, Clerk Co. Court, LC / A. H. Sandell, Deputy (per [112] source text). ⚠️ Prior entry cited V.E. Brogden as clerk — discrepancy flagged; see PHASE_1.txt [22] notes. Execution date: **Oct 13, 1906** (corrected from Oct 12; per deed body "this 13th day of Oct. A.D. 1906"). Scrivener's errors in original instrument: "M. J. Bounds" (= M. S. Bounds grantee), "Book S page 661" (= Book G p.661 per [116] confirmation), "H. & D.C. R.R." (= H. & T.C. R.R.), "the some" (= "the same"). Consideration: $520 cash + 4×$440 VL notes = $2,280 ($2,280.76 stated in deed body — minor discrepancy). JH Bounds alive and personally participating. Notary: S. B. Poindexter, Freestone County. |
| [104] | J. H. Bounds → W. G. Eades | Limestone | ✓ | Vol. 2, Pg. 528 [INDEX CONFIRMED: LC Vol.2 Pg.528, 2026-03-08] | — | Jun 19, 1888 | Jun 19, 1888 | W. F. Brown, Clerk / H. W. Williams, Deputy, LC; 2 ac, Block 19, Town of Tehuacana, John Boyd League; $315 vendor's lien notes; Acknowledged before W. Allegra JP, Freestone County, March 31, 1885; warranty with vendor's lien, surface+minerals, no reservations; sell-out pre-dating [106] Haley acquisition |
| [106] | Hiram Haley and Sinai A. Haley → J. H. Bounds | Limestone | ✓ | Volume/page not stated in transcription; **PROBABLE**: Vol. 2, Pg. 381 per LC index (Inst# DR-00002-00381, recorded 12/17/1887, HALEY K H + → BOUNDS J H, J BOYD SUR, 158 ACRES) — ⚠️ grantor name discrepancy: index says "HALEY K H" vs transcription "Hiram Haley"; all other fields match; requires verification pull at Vol. 2 Pg. 381 [INDEX PROBABLE: LC Vol.2 Pg.381, 2026-03-09] | — | Dec 17, 1887 | Dec 17, 1887 | W. F. Brown, Clerk / H. Williams, Deputy, LC; 156 net ac, John Boyd Survey; $2,000 cash; Acknowledged before A. E. Firmin NP, Limestone County, December 27, 1886; warranty deed, surface+minerals, no reservations; Sinai A. Haley privy examination before same notary |
| [108] | J. H. Bounds and wife M. E. Bounds → J. W. Bounds ⚠️ [INDEX GRANTEE DISCREPANCY: LC index (Inst# DR-0000S-00582) shows grantee as "BOUNDS T W" — not "J W" — consistent with Theophilus Walton Bounds; see PM Report Section 3.2 and ISSUE-32 update; HUMAN VERIFICATION REQUIRED against original instrument, 2026-03-08] | Limestone | ✓ | Vol. S, Page 582 [INDEX CONFIRMED: LC Vol.S Pg.582, 2026-03-08] | 582 | Apr 1, 1889 | Apr 1, 1889 | W. F. Brown, Clerk / Deputy name illegible, LC; 156 net ac, John Boyd Survey; $5 + natural love and affection (gift to son); Acknowledged before J. E. Longbotham NP, Freestone County, March 27, 1889; M. E. Bounds privy examination before same notary; warranty/gift deed, surface+minerals, no reservations |
| [113] | J. M. Barry et al. → W. L. Adams and W. S. Adams | Limestone | ⬜ | Vol. 63, Pg. 167 [INDEX CONFIRMED: LC Vol.63 Pg.167, 2026-03-08] | — | May 11, 1910 | May 11, 1910 | W. C. Frazier, Clerk / N. H. Sandell, Deputy, LC; 338 ac multi-survey (162 ac Varela + 96 ac Norvelle + 80 ac Boyd League); $5,250 cash; multiple acknowledgments including S. B. Poindexter NP Freestone County (MS Bounds and Mattie Bounds, April 1, 1910); warranty deed, surface+minerals, no reservations; ⚠️ execution date 1910-03-22 is triage catalog only — not confirmed in deed source file; ⚠️ triage catalog only — not PDF-verified |
| [114] | J. M. Barry et al. → W. J. Robinson | Limestone | ⬜ | Vol. 63, Pg. 405 [INDEX CONFIRMED: LC Vol.63 Pg.405, 2026-03-08] | — | Nov 28, 1910 | Nov 28, 1910 | W. C. Frazier, Clerk / J. H. Pritchard, Deputy, LC; 43 ac, P. Varela Survey; $535.05 ($107.05 cash + three vendor's lien notes of $154.80 each); MS Bounds and Mattie Bounds acknowledged before Geo. A. Bell NP, Limestone County; ⚠️ execution date 1910-07-10 is triage catalog only — not confirmed in deed source file; ⚠️ ACKNOWLEDGMENT DATE ANOMALY: some ack dates appear to be February 10, 1910, before the July 10 deed date — cannot resolve without examining original; ⚠️ triage catalog only — not PDF-verified |
| [01] | Bessie Plunkett et al → MS Bounds | Freestone | ✓ | Deed Record Vol. 244 | 592–594 | Dec 2, 1953 | Dec 19, 1953 | Henry McCormick |
| [02] | MS Bounds et ux → Hugh David Vickers | Freestone | ✓ | File No. 388; Deed Record Vol. 193 [INDEX CONFIRMED: FC DR/193/96, Doc# 1947-388, 2026-03-09] | 96–97 | Jan 30, 1947 at 1:00 PM | Feb 5, 1947 at 11:15 AM | Henry McCormick |
| [03] | Gussie Weaver et ux (Jewell Weaver) → JP Black | Freestone | ✓ | File No. 2519; Deed Record 262 [INDEX CONFIRMED: FC DR/262/271, Doc# 1955-2519, 2026-03-09] | 271–272 | Oct 27, 1955 at 3:20 PM | Dec 27, 1955 at 2:00 PM | Henry McCormick; Notary: Walter T. Thomason (Freestone Co.); Ack. date: Sep 24, 1955; MINERAL SEVERANCE by both grantors ("reserved to the grantors herein") |
| [04] | MS Bounds → Olena Black | Freestone | ✓ | Deed Record 419, Inst. 3033 | 676–677 | Oct 24, 1972 | Nov 1, 1972 | Henry McCormick / Sue Lambert dep. |
| [05] | MS Bounds → Olena Black | Freestone | ✓ | Deed Record 419 | 673–675 | Oct 24, 1972 | Nov 1, 1972 | Henry McCormick / Sue Lambert dep. |
| [23] | MS Bounds → Olena Black | Limestone | ✓ | Vol. 575, File No. 6178 | 457 | Oct 10, 1972 | Oct 13, 1972 | Dena Pruitt / Starlet Ross dep. |
| [07] | Estate of M.S. Bounds, Deceased (Olena Black, Executrix) → Olena Black | Freestone | ✓ | Deed Record 545, Inst. 8245 | 822–824 | Dec 27, 1979 | Dec 28, 1979 | Doris Terry Welch / Mary Lynn White dep. |
| [24] | Verona E. Black → Georgia Nell Ennis, Genevieve Dorsett, John P. Black | Limestone | ✓ | Doc 07507434, Bk OPR, Vol. 592, Pg. 773, filed Jan 3, 1975 04:00 PM [INDEX CONFIRMED: LC Inst# 07507434, 592/773, 2026-03-09] | — | Dec 30, 1974 | Jan 3, 1975 | Dena Pruitt; Notary: Roy Simmons (Limestone Co.); Ack. date: Dec 30, 1974; surface+minerals; full warranty; no reservations; three PDF bearing corrections to Second Tract (see bearing issues section). **Note**: Roy Simmons (notary on this deed) purchased the same property 19 days later — see deed [318]. **DISPOSED**: entire ~42.8 ac Boyd Survey sold to Simmons (01/18/1975). ISSUE-01 RESOLVED. |
| [318] | Georgia Nell Ennis + Genevieve Dorsett + John P. Black → Roy Simmons and wife Virginia M. Simmons | Limestone | ✓ | LC Pg. 328–330, Doc# 489 (Inst# 07500489). Filed Jan 22, 1975 at 10:50 AM; recorded Jan 27, 1975 at 4:00 PM; Starlet Ross, Deputy; Dena Pruitt, County Clerk; Limestone County. | 328–330 (3 pages) | 1975-01-18 | 1975-01-27 | **Warranty Deed with Vendor's Lien** — DISPOSED PROPERTY (Boyd Survey). ALL grantors' Limestone County property: three John Boyd Survey tracts (First Tract 16.8 ac, Second Tract 25 ac, Third Tract ~1 ac less 100×100 ft lot) = ~42.8 ac total. Same three tracts as deed [24]. Consideration: $10.00 + $12,800 promissory note (vendor's lien retained). Deed of trust to L. L. Dorsett, trustee. Mineral reservation: 1/16 NPRI for 10 years only — expired January 1985. Roy Simmons was notary on deed [24]. Ennis acknowledged Jan 18, 1975 before Geraldine Fender NP, LC; JP Black acknowledged Jan 18, 1975 before Geraldine Fender NP, LC; Dorsett acknowledged Jan 20, 1975 before Lois S. Moore NP, Jefferson County, Alabama (commission exp. Apr 23, 1976). Genevieve's acknowledgment captioned "State of Texas" corrected to "State of Alabama." Companion vendor's lien release: LC Inst# 07804491, Vol. 630, Pg. 105 (06/13/1978). **Entire Boyd Survey holding permanently left family chain.** ISSUE-01 RESOLVED. ISSUE-43 item 11. Phase 2 |
| [27] | Olena Black → James Allen Black | Limestone | ✓ | LC Vol. 649, Pg. 815, Doc# 08000176 [INDEX CONFIRMED: LC Vol.649 Pg.815, 2026-03-09] ⚠️ CONFLICT: PDF showed "Page 176" — HUMAN VERIFICATION REQUIRED | — | Jan 4, 1980 | Jan 15, 1980 | Dena Pruitt / Joan Schmidt dep. |
| [28] | Olena Black → John Marion Black | Limestone | ✓ | LC Vol. 649, Pg. 816, Doc# 08000177 [INDEX CONFIRMED: LC Vol.649 Pg.816, 2026-03-09] ⚠️ CONFLICT: PDF showed "Page 177" — HUMAN VERIFICATION REQUIRED | — | Jan 4, 1980 | Jan 15, 1980 | Dena Pruitt / Joan Schmidt dep. |
| [29] | Olena Black → James Allen Black | Limestone | ✓ | LC Vol. 665, Pg. 799, Doc# 08011822 [INDEX CONFIRMED: LC Vol.665 Pg.799, 2026-03-09] | — | Dec 16, 1980 | Dec 19, 1980 | Dena Pruitt / Dean Granon dep. |
| [30] | Olena Black → John Marion Black | Limestone | ✓ | LC Vol. 665, Pg. 798, Doc# 08011821 [INDEX CONFIRMED: LC Vol.665 Pg.798, 2026-03-09] | — | Dec 16, 1980 | Dec 19, 1980 | Dena Pruitt / Dean Granon dep. |
| [10] | Olena Black → James Allen Black | Freestone | ✓ | Vol. 898, Pages 78–80 | — | Jan 22, 1993 | — | Mary Lynn White / deputy sig. illegible; gift tax Year 1 of 2-year split; parcel physically in Limestone County (see survey history note below) |
| [31] | Olena Black → James Allen Black | Limestone | ✓ | Vol. 1043, Pages 221–223 | — | Sep 29, 2000 | Oct 2, 2000 at 4PM | Sue Lown / Lynne Jones dep. (same instr. as [10], re-filed 8 yrs later) |
| [11] | Olena Black → James Allen Black | Freestone | ✓ | Vol. 898, Pages 81–83 | — | Jan 22, 1993 | — | Mary Lynn White / deputy sig. illegible; filing time ambiguous (9:00 or 2:00 A.M.); gift tax Year 2 of 2-year split; parcel physically in Limestone County (see survey history note below) |
| [32] | Olena Black → James Allen Black | Limestone | ✓ | Vol. 1043, Pages 224–226 | — | Sep 29, 2000 | Oct 2, 2000 at 4PM | Sue Lown / Lynne Jones dep. (same instr. as [11], re-filed 7+ yrs later); Freestone stamp on this copy shows Lynne Jones as deputy |
| [13] | Olena Black → Texas Utilities Electric Co. | Freestone | ✓ | Vol. 1004, Pages 286–290 | — | Jan 29, 1997 at 10:45 a.m. | — | Mary Lynn White / Kim Terry, Deputy; CRITICAL: reverter clause — conveyance void if premises cease use for rail transport to Big Brown SES. NOT found in F-TXU index (predates 1999 coverage; entity name "Texas Utilities Electric Co" not indexed under "TXU" — separate "TEXAS UTILITIES" search needed). Corporate succession: TXU Electric Co → TXU Big Brown Co LP (FC 2001-1008387, 12/20/2001, scope TBD) → Big Brown Power Co LLC (FC 2007-707919, 10/11/2007). County deed index search (3 indices, 721 records) found zero rail spur abandonment/reconveyance instruments. |
| [35] | Estate of Olena Bounds Black → John Marion Black | Limestone | ✓ | Vol. 1179, Pages 553–558, Doc. 00053259 [INDEX CONFIRMED: LC Vol.1179 Pg.553, Doc# 00053259, 2026-03-09] | — | Jul 18, 2005 at 09:32 a.m. | — | Sue Lown / Diane Tilley, Deputy; partition deed — 18.00 ac (Tract One) to JMB; remainder of 92 ac First+Fourth Tracts back to Estate; Execution Date Jul 7, 2005; Effective Date Mar 28, 2005 (Olena's death — retroactive 102 days); Prepared by Geneva Brown Turner, Esq., Pakis Giotes Page & Burleson P.C.; SCRIVENER ERROR: deed uses "A-17" throughout — correct abstract is A-19 (see survey history note below; annotated [sic] in PHASE_3.txt) |
| [06] | John Pierce Black (Trustor) → Trust | Freestone | ✓ | Deed Record 531, Pages 498–499 | — | May 29, 1979 at 10:00 a.m. | June 1, 1979 | Doris Terry Welch / Sue Barnett, Deputy; trust memorandum — JPB Family Trust of 1977; same instrument as [25] filed in Limestone |
| [25] | John Pierce Black (Trustor) → Trust | Limestone | ✓ | LC Vol. 641, Pg. 764, Doc# 07904374 [INDEX CONFIRMED: LC Vol.641 Pg.764, 2026-03-09] (Prior entry showed DR 531/498-499 — this was the FC stamp on the LC copy; true LC citation now confirmed) | — | June 7, 1979 at 8:00 a.m. | June 8, 1979 at 4:00 p.m. | Dena Pruitt / Nancy Stockton, Deputy; trust memorandum — JPB Family Trust of 1977; same instrument as [06] filed in Freestone |
| [08] | Olena Bounds Black (Indiv. + Exec.) → JPB Family Trust of 1977 | Freestone | ✓ | Deed Record 531, Pages 500–502 | — | May 29, 1979 at 10:00 a.m. | June 1, 1979 | Doris Terry Welch / Sue Lambert, Deputy; warranty deed — Tracts 1+2 surface+improvements; MINERAL SEVERANCE RESERVED by grantor; effective date May 23, 1979 |
| [09] | Olena Bounds Black → JPB Family Trust of 1977 | Freestone | ✓ | Deed Record 541, Page 463 | — | Oct 17, 1979 at 11:00 a.m. | Oct 19, 1979 | Doris Terry Welch / Donna Louise, Deputy; quitclaim — 85.3 ac Sarah McAnulty Survey; same tract as [08] Tract 1; HABENDUM DEFECT: "unto the said OLENA BOUNDS BLACK" names grantor in grantee position — scrivener's error; see ISSUE-22 |
| [26] | JPB Family Trust of 1977 → Olena Bounds Black | Limestone | ✓ | LC Vol. 641, Pg. 766, Doc# 07904375 [INDEX CONFIRMED: LC Vol.641 Pg.766, 2026-03-09] | — | June 7, 1979 at 8:00 a.m. | June 8, 1979 at 4:00 p.m. | Dena Pruitt / Nancy Stockton, Deputy; quitclaim — Trust quitclaims community property residence back to Olena; 20-ac Exhibit A; reverse direction from other trust-funding deeds |
| [12] | NationsBank of Texas N.A. (succ. to Citizens National Bank) + Olena Bounds Black → M. Stephen Beard as Successor Co-Trustee | Freestone | ✓ | Vol. 0953, Pages 040–042 | — | Mar 15, 1995 at 9:00 a.m. | — | Mary Lynn White / Lynne Jones, Deputy; distribution deed — trustee change from Citizens/NationsBank to M. Stephen Beard; no warranty |
| [14] | Estate of Olena Bounds Black → Trust No. 1, M. Stephen Beard Sole Trustee | Freestone | ✓ | FC OR Vol. 1327, Pg. 554, Doc No. 05004968 [INDEX CONFIRMED: FC OR/1327/554, 2026-03-08] | — | Jul 18, 2005 at 02:35P | — | Mary Lynn White / Gena Aultman, Deputy; distribution deed — 4 tracts from Olena estate: Tract One (Freestone, 9 sub-tracts gross 491.99 ac less 162.99 ac Exhibit B = 329 ac net), Tract Two (3 ac Limestone McAnulty, 1859 Manning→Bounds), Tract Three (states 92 ac — scrivener's error; correct is 74 ac after [35] partition; ISSUE-23), Tract Four (92 ac cross-county McAnulty); No mineral reservation; dual-filed = [36] |
| [36] | Estate of Olena Bounds Black → Trust No. 1, M. Stephen Beard Sole Trustee | Limestone | ✓ | Doc No. 00053439, Vol. 1180, Pg. 449–456 | — | Jul 27, 2005 at 10:35A | — | Sue Lown / Jennifer Johnson; same instrument as [14]; same Tract Three scrivener's error (92 ac stated, 74 ac correct; ISSUE-23); Limestone filing confirmed cross-county coverage; notary: Geneva B. Turner (exp. 04/14/2008); attorney: Geneva Brown Turner, Pakis Giotes Page & Burleson |
| [15] | Estate of Olena Bounds Black → Trust No. 1 (1/2) + Trust No. 2 (1/2), M. Stephen Beard Sole Trustee | Freestone | ✓ | FC OR Vol. 1327, Pg. 568, Doc# 2005-5004970 [INDEX CONFIRMED: FC OR/1327/568, 2026-03-08]. Filed Jul 18, 2005. Index: MINERAL DEED, BLACK OLENA BOUNDS DECEASED ESTATE OF → BLACK OLENA BOUNDS ESTATE TRUST #1, WORTHAM TOWN OF 6-7 0006. | — | — | — | Special warranty mineral deed; minerals only (0.09 ac Wortham lots); notary: Geneva B. Turner (exp. 04/14/2008); attorney: Geneva B. Turner, Pakis Giotes Page & Burleson; execution date Jul 7, 2005 |
| [16] | Estate of Olena Bounds Black → Trust No. 2, M. Stephen Beard Sole Trustee | Freestone | ✓ | FC OR Vol. 1327, Pg. 561, Doc# 2005-5004969 [INDEX CONFIRMED: FC OR/1327/561, 2026-03-08]. Filed Jul 18, 2005. Index: DEED, BLACK OLENA BOUNDS DECEASED ESTATE OF → BLACK OLENA BOUNDS ESTATE TRUST #2. | — | — | — | Distribution deed; dual-filed = [37]; 4 tracts (Richie 317.50 ac, Beldin 33.66 ac, 162.99 ac carved, 20 ac McAnulty cross-county); notary: Geneva B. Turner (exp. 04/14/2008); attorney: Geneva Brown Turner, Pakis Giotes Page & Burleson; execution Jul 7, 2005; effective Mar 28, 2005 |
| [37] | Estate of Olena Bounds Black → Trust No. 2, M. Stephen Beard Sole Trustee | Limestone | ✓ | Doc 00053440, Bk RP, Vol. 1180, Pg. 457 | — | — | — | SAME INSTRUMENT AS [16]; Limestone County filing |
| [18] | JP Black Family Trust of 1977 → Trust No. 1, M. Stephen Beard Sole Trustee | Freestone | ✓ | FC OR Vol. 1327, Pg. 546, Doc# 2005-5004965 [INDEX CONFIRMED: FC OR/1327/546, 2026-03-09]. Filed Jul 18, 2005. Index: DEED, BLACK JOHN PIERCE FAMILY TRUST OF 1977 → BLACK JOHN PIERCE ESTATE TRUST #1, S MC ANULTY SUR 85.3 ACS. | — | — | — | Distribution deed; Edwards Tract 85.30 ac, Sarah McAnulty Survey A-751, Freestone County; source deed for Edwards Tract flowing into Trust No. 1. |
| [19] | JP Black Family Trust of 1977 → Trust No. 2, M. Stephen Beard Sole Trustee | Freestone | ✓ | FC OR Vol. 1327, Pg. 549, Doc# 2005-5004966 [INDEX CONFIRMED: FC OR/1327/549, 2026-03-09] [CAD CONFIRMED: FC CAD parcel 17560, 2026-03-10]. Filed Jul 18, 2005. Index: DEED, BLACK JOHN PIERCE FAMILY TRUST OF 1977 → BLACK JOHN PIERCE ESTATE TRUST #2, W RITCHIE SUR 39.5 ACS. | — | — | — | Distribution deed; Weaver Tract (33.61 ac, W. Richie A-527); surface only (minerals severed in [03]); index states 39.5 ACS — references parent tract acreage, not net; no conflict with 33.61 ac. |
| [17] | Trust No. 1 → Trust No. 2, M. Stephen Beard Sole Trustee (both sides) | Freestone | ✓ | FC OR Vol. 1327, Pg. 571, Doc# 2005-5004971 [INDEX CONFIRMED: FC OR/1327/571, 2026-03-08]. Filed Jul 18, 2005. Index: MINERAL DEED, BLACK OLENA BOUNDS ESTATE TRUST #1 → BLACK OLENA BOUNDS ESTATE TRUST #2. | — | — | — | Special warranty mineral deed; dual-filed = [38]; 1/2 mineral interest in 5 tracts + executive rights retained by Trust 1; notary: Geneva B. Turner (exp. 04/14/2008); attorney: Geneva B. Turner, Pakis Giotes Page & Burleson; PDF-CONFIRMED DEFECTS: (1) acknowledgment identifies Beard as Trust No. 2 trustee — grantor is Trust No. 1 (ISSUE-25); (2) Exhibit C blank page number "Volume 35, Page _" (ISSUE-28); (3) Exhibit A Sixth Tract "S. Slaughter" (ISSUE-27) |
| [38] | Trust No. 1 → Trust No. 2, M. Stephen Beard Sole Trustee (both sides) | Limestone | ✓ | Doc 00053441, Bk RP, Vol. 1180, Pg. 465 | — | — | — | SAME INSTRUMENT AS [17]; Limestone County filing; carries same defects (ISSUE-25, ISSUE-27, ISSUE-28) |
| [20] | Trust No. 2 → Trust No. 1, M. Stephen Beard Sole Trustee (both sides) | Freestone | ✓ | FC OR Vol. 1327, Pg. 579, Doc 05004972 [INDEX CONFIRMED: FC OR/1327/579, 2026-03-08], filed Jul 18, 2005 at 2:35PM; Mary Lynn White County Clerk; Gena Aultman Deputy; $28.00 fee; Receipt 61253 | — | — | — | Special warranty mineral deed; dual-filed = [39]; 1/2 mineral interest in 5 Trust 2 surface tracts + executive rights retained by Trust 2; bilateral equalization partner to [17]; ⚠️ Tract Five conveys zero mineral interest in Weaver Tract (ISSUE-29) |
| [39] | Trust No. 2 → Trust No. 1, M. Stephen Beard Sole Trustee (both sides) | Limestone | ✓ | Doc 00053442, Bk RP, Vol. 1180, Pg. 474 | — | — | — | SAME INSTRUMENT AS [20]; Limestone County filing; LC docs 00053439–00053442 are sequential confirming coordinated closing |
| [21] | Trust No. 1 (Donald Fredrick Willis Jr., Sole Trustee) → Gude Management LLC | Freestone | ✓ | Instrument No. 2600106, recorded Jan 12, 2026 08:04 AM eRecording, Renee Gregory County Clerk, 8 pages, $49.00 fee, Receipt 20260112000001 | — | 2026-01-08 | — | Special warranty deed; surface+minerals; Consideration $10.00; Tract One (Exhibit A 9 sub-tracts, Strickland A-550/Slaughter A-565/Curry A-9, 329 ac net less Exhibit B 162.99 ac) + Tract Two (First Tract, 92 ac stated [sic — 74 ac actual; ISSUE-23]) + Tract Four (Fourth Tract, 92 ac cross-county McAnulty); ⚠️ NO Tract Three — Manning parcel omitted (ISSUE-30); ⚠️ Edwards Tract (A-751, 85.30 ac) absent (ISSUE-31); ⚠️ Wortham Lots absent (ISSUE-24); Acknowledged Harris County Jan 8, 2026; Notary: Destinee Leeanne Reyes ID #13363853-5 exp. Mar 10 2026; Preparer: Dore Rothberg Law P.C., Houston; No-title-search disclaimer present; RESERVATIONS: None; ISSUE-27 (S. Slaughter [sic] Exhibit A Sixth Tract) confirmed; dual-filed = [40]; NOTE: FC filing = 8 pages, LC filing = 7 pages |
| [40] | Trust No. 1 (Donald Fredrick Willis Jr., Sole Trustee) → Gude Management LLC | Limestone | ✓ | Doc 2026-0000082, recorded Jan 12, 2026 08:46:48 AM eRecording, Kerrie Cobb County Clerk, 7 pages | — | 2026-01-08 | — | SAME INSTRUMENT AS [21]; Limestone County filing; identical body text, exhibits, signatures, notary, and preparer information per PDF review; same tract omissions (ISSUE-30, ISSUE-31, ISSUE-24); eRecording submitted by dore law group p.c., 17171 Park Row Ste 160, Houston TX 77084-4927 — NOTE: different address from deed preparer block (16225 Park Ten Place Dr. Suite 700) — firm may have relocated between deed drafting and LC filing |
| [33] | James Allen Black → John Marion Black | Limestone | ✓ | LC Vol. 1179, Pg. 562, Doc# 00053261 [INDEX CONFIRMED: LC Vol.1179 Pg.562, 2026-03-09] | — | 2005-07-07 | — | Special warranty mineral deed; minerals only (undivided 1/2 of James's mineral interest in L20555, Fifth Tract 18 ac, Sarah McAnulty Survey, Limestone County); James retains executive rights (right to lease); consideration $10.00; acknowledged McLennan County Jul 7, 2005; notary: Geneva B. Turner (exp. 04/14/2008); preparer: Geneva Brown Turner, Esq., Pakis Giotes Page & Burleson P.C.; Limestone County only (no Freestone filing — surface parcel is entirely within Limestone County) |
| [34] | John Marion Black → James Allen Black | Limestone | ✓ | LC Vol. 1179, Pg. 559, Doc# 00053260 [INDEX CONFIRMED: LC Vol.1179 Pg.559, 2026-03-09] | — | 2005-07-07 | — | Special warranty mineral deed; minerals only (undivided 1/2 of John Marion's mineral interest in L20556, partition parcel 18 ac, Sarah McAnulty Survey, Limestone County); John Marion retains executive rights (right to lease); consideration $10.00; acknowledged McLennan County Jul 7, 2005; notary: Geneva B. Turner (exp. 04/14/2008); preparer: Geneva Brown Turner, Esq., Pakis Giotes Page & Burleson P.C.; Exhibit A metes-and-bounds attached; SCRIVENER ERROR: deed body and Exhibit A both use "A-17" — correct abstract for Limestone County McAnulty parcels is A-19 (see ISSUE-20; annotated [sic] in PHASE_7.txt); Limestone County only |
| [115] | MS Bounds + Mattie Bounds — Homestead Designation | Limestone + Freestone | ✓ | LC: Vol. 233, Pg. 136 [INDEX CONFIRMED: LC Vol.233 Pg.136, 2026-03-08]. FC: DR Vol. 128, Pg. 18, Doc# 1934-420 [INDEX CONFIRMED: FC DR/128/18, 2026-03-08]. Filed Feb 8, 1934; recorded Feb 8, 1934; Anna Burney, County Clerk, Limestone County; Deputy [illegible]arten. ⚠️ Freestone County filing CONFIRMED by FC index — answers prior open question. | — | 1934-02-03 | 1934-02-08 | Homestead designation only; no conveyance; 200 ac in 2 tracts (20 ac McAnulty = deed [22] Third Tract; 180 ac Richie League FC). ⚠️ Freestone County filing question: instrument describes a Freestone County tract (180 ac Wm Richie League) but was filed only in Limestone County per triage catalog — verify whether a separate Freestone County filing exists (see ISSUE flagged in Session 4). Execution date per deed text: "3rd day of February, 1934." |
| [116] | MS Bounds → Mrs. Mattie Bounds (inter-spousal separate property) | Limestone | ✓ | Vol. 252, Pg. 463, Limestone County. Filed Aug 2, 1937; recorded Aug 5, 1937; W. L. Bond, County Court Clerk; Nola Oates, Deputy. ⚠️ Vol/Pg confirmed by deed [118] cross-reference only — not direct notation in [116]'s own recording stamp as transcribed; verify against original. | — | 1937-07-31 | 1937-08-05 | Warranty deed; five McAnulty tracts (94+20+2+92+18 = 226 ac stated) as Mattie's separate property; grantee takes subject to Federal Land Bank loan; consideration $10 + loan repayment + love/affection. ⚠️ 226 ac vs. 224 ac discrepancy with deed [118] (ISSUE-36). |
| [117] | Federal Land Bank of Houston — Release of Lien | Limestone | ✓ | Filed Sep 18, 1945; recorded Sep 20, 1945; John Kidd, County Clerk; Mary Jo Baker, Deputy; Limestone County. Margin notation: "***5059***" (instrument number or index reference). ⚠️ TRIAGE CATALOG ONLY for filing/recording dates — not PDF-verified. Vol/Pg not stated; pull from Limestone County records. | — | 1945-09-13 | 1945-09-20 | Release of deed of trust; releases Federal Land Bank Loan F-13491 ($3,300 principal); underlying deed of trust: Jan 22, 1934, Vol. 2-A p.278 LC. DOES NOT address 1906 vendor's lien (ISSUE-14) — different instrument entirely. |
| [118] | Mattie Bounds et vir MS Bounds → State of Texas (Highway ROW) | Limestone | ✓ | Filed Mar 17, 1960; recorded Mar 23, 1960; John Kidd, County Clerk; Dana Little, Deputy; Limestone County. Form: Texas Highway Department Form D-15-14-57. ⚠️ TRIAGE CATALOG ONLY for filing/recording dates — not PDF-verified. Vol/Pg not stated; pull from Limestone County records. | — | 1960-03-15 | 1960-03-23 | Warranty deed; 2.731 ac ROW in 2 tracts (Tract 1: 0.650 ac from 18-ac Fifth Tract; Tract 2: 2.081 ac from 20-ac Second Tract); minerals reserved (oil/gas/sulphur) with ingress/egress waiver; parent tract described as "224-acre tract" (⚠️ ISSUE-36: deed [116] five-tract sum = 226 ac); wife identified as "Mrs Mattie S. Bounds" — middle initial S unexplained in prior instruments (⚠️ ISSUE-37). |
| [119] | J. H. Bounds → Houston & Texas Central Railway Co. | Limestone | IDX | LC Vol. D, Pg. 24, Inst# DR-0000D-00024 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 03/22/1875 | — | McAnulty League railroad ROW conveyance. The H&TC ROW runs through the McAnulty League and is the boundary feature that diminishes the Manning 3-acre Second Tract to 2 ac net. Referenced as boundary call in deeds [22], [05]/[23], [116] and all downstream instruments. **DISPOSED — ROW CONVEYANCE OUT. NO REVERSION CLAUSE IN INDEX.** Pull PDF to confirm terms. |
| [120] | J. H. Bounds → J. E. Bounds | Limestone | IDX | LC Vol. F, Pg. 584, Inst# DR-0000F-00584 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 02/26/1877 | — | Gift deed; 158 acres, John Boyd League. Earliest documented JH Bounds Boyd Survey disposition — predates the Haley acquisition ([106]) by 9 years, confirming JH Bounds held Boyd Survey land before 1886. J.E. Bounds is a JH Bounds son (appears in 1906 deed [111] grantor list). **DISPOSED OUT OF DIRECT CHAIN.** Downstream disposition of J.E. Bounds' 158 ac not yet documented — pull PDF; chain research needed (see ISSUE-32 update). |
| [121] | J. H. Bounds → J. V. Bounds | Limestone | IDX | LC Vol. F, Pg. 585, Inst# DR-0000F-00585 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 02/26/1877 | — | Gift deed; 62 acres, John Boyd League. Same date as [120] — coordinated distribution. J.V. Bounds is a JH Bounds son (appears in 1906 deed [111] grantor list). **DISPOSED OUT OF DIRECT CHAIN.** Downstream disposition of J.V. Bounds' 62 ac not yet documented — pull PDF; chain research needed (see ISSUE-32 update). |
| [122] | T. W. Bounds → Brown James et al. | Limestone | IDX | LC Vol. 13, Pg. 301, Inst# DR-00013-00301 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 11/13/1891 | — | Deed; 158 acres, John Boyd Survey. T.W. Bounds reconveys the [106]/[108] 158-acre Boyd parcel to Brown James and others approximately 2.5 years after receiving it as a gift. **DISPOSED — NO REVERSION.** The [106]/[108] parcel permanently left the family chain in 1891. This definitively rules out [106]/[108] as the upstream source of deed [24]. ⚠️ Subject to resolution of ISSUE-32 T.W./J.W. name discrepancy — pull original to confirm grantor identity matches [108] grantee. |
| [123] | J. H. Bounds et al. → Dunbar H. Clay et al. | Limestone | IDX | LC Vol. 48, Pg. 373, Inst# DR-00048-00373 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 08/16/1906 | — | Deed; McAnulty League (acreage not stated in index). Pre-partition McAnulty disposition — recorded August 16, 1906, approximately two months before the coordinated October 1906 family partition (deeds [111] and [22]). May explain part of the gap between the "361 acres tract" reference in deed [111] and the 223.25-acre 1906 partition total. **DISPOSED OUT OF DIRECT CHAIN** pending PDF pull. Pull to confirm acreage and tract description; update ISSUE-34 arithmetic. |
| [124] | J. H. Bounds → T. W. Bounds | Limestone | IDX | LC Vol. 52, Pg. 177, Inst# DR-00052-00177 [INDEX IDENTIFIED: LC, 2026-03-08] | — | — | 12/21/1906 | — | Deed; 9 acres (survey not stated in index). JH Bounds conveying 9 acres to T.W. Bounds in December 1906, two months after the coordinated McAnulty partition. Survey and tract identity unknown from index alone. Pull PDF to determine survey, tract description, and relevance. ⚠️ T.W. Bounds identity subject to ISSUE-32 resolution. |
| [321] | M. Stephen Beard (Attorney of Record, Estate of JP Black) → Public | Limestone | ✓ | LC Vol. 640, Pg. 821, Inst# 07903577 [INDEX CONFIRMED: LC Vol.640 Pg.821, 2026-03-09] | 821–823 (3 pages) | 1979-05-10 (8:00 AM) | 1979-05-11 (4:00 PM) | Dena Pruitt, County Clerk, Limestone County; Deputy: Nancy Stockton. **Affidavit of No Inheritance Tax Due** — Probate No. 4476, Limestone County, Estate of John Pierce Black, Deceased. M. Stephen Beard (Pakis, Cherry, Beard & Giotes, Inc., 8th Floor, First National Bldg., Waco TX 76701) attests: (1) he is Attorney of Record for the Estate; (2) State Inheritance Tax Return filed; (3) Comptroller certificate of no tax due received (Exhibit A, signed Bob Bullock, 4/27/1979); (4) Certificate releasing Olena Bounds Black, Independent Executrix (Route 1, Box 166, Wortham TX 76693), from personal liability received (Exhibit B, signed Bob Bullock, 4/27/1979); (5) no federal estate tax liability. Sworn before Margaret Dickens, Notary Public, McLennan County (comm. exp. 8/31/1980). Acknowledged same date before same notary. Tax clearance instrument — no conveyance. Phase 4 |
| [331] | Estate of Olena Bounds Black (JMB+JAB Independent Co-Executors) → Charles L. Calame and wife Dorothy Calame | Freestone | ✓ | FC Doc# 06000827, OR Vol. 1350, Pg. 233–235, filed Feb 14, 2006, Mary Lynn White County Clerk, Linda Jarvis Deputy, $24.00 fee, Receipt 65851 | 233–235 (3 pages) | — | 2006-02-14 (10:11 AM) | Special warranty deed; **surface only** (0.0918 ac, Lots 6 & 7, Block 6, Town of Wortham, R.B. Longbotham Survey A-16, Freestone County); MINERAL RESERVATION: all oil, gas, and other minerals reserved to Grantor and heirs/successors/assigns forever; consideration $10.00 + OGVC; source deed: Rice Institute → M.S. Bounds, Jan 18, 1918, Vol 64 p.173 FC (same source as deed [15]); execution date Jul 7, 2005; acknowledged McLennan County Jul 7, 2005; notary: Geneva B. Turner (exp. 04/14/2008); preparer: Geneva Brown Turner, Esq., Pakis Giotes Page & Burleson P.C., 801 Washington Ave Suite 800, Waco TX 76701-1289, (254) 297-7300; Calame address: 401 South Avenue B, Wortham, Freestone County TX 76693; **companion surface deed to mineral deed [15]** — same property, same date, same attorney, same notary; [15] filed Jul 18, 2005; [331] filed Feb 14, 2006 (7-month filing delay); Phase 5 |
| [338] | Estate of John M. Black, Deceased (Kay L.R. Black, Indep. Executrix) → Kay L.R. Black | Limestone | ✓ | LC Doc# 2025-0004419, recorded 11/17/2025 10:46:22 AM, Kerrie Cobb County Clerk, 6 pages (incl. cover page) | — | 2025-10-27 | 2025-11-17 | Administration Deed; 18.00 ac Sarah McAnulty Survey A-17 [sic — A-19] (ISSUE-20), Limestone County; partition parcel L20556, carved entirely from First Tract (deed [338] calls First Tract "92 acres" — ISSUE-23 error; correct is 74 ac after [35] partition); source deed: Vol. 575 Pg. 457 LC = deed [05]/[23]; consideration $10.00 + OGVC; no mineral reservation — surface + JM Black's 1/2 mineral interest + executive rights convey to Kay; standard exceptions (existing mineral interests outstanding in persons other than Grantor = James Allen Black's 1/2 non-exec per [34]); Exhibit A full metes-and-bounds (bounded by UP RR west, LCR 251 north, Tehuacana Creek south); acknowledged Fort Bend County 10/28/2025; notary: Tracy Nicole Levy (ID 133682184, exp. 4/1/2026); preparer: Duff Drozd Law PLLC, 210 Main Street, Richmond TX 77469; **confirms JM Black estate formally probated, Fort Bend County**; ISSUE-05 partially resolved; Phase 7 |
| — | 2025-04-04 | LC Inst# 2025-0001187 | AFFIDAVIT | WILLIS DONALD FRED JR + | PUBLIC | Limestone | ⬜ | INDEX IDENTIFIED: LC, 2026-03-09. Grantor: "WILLIS DONALD FRED JR +". **Updated (2026-03-30)**: The Beard→Willis transition instrument has been located as a private unrecorded document (Trustee Resignation and Appointment, effective 5/1/2017, notarized 10/24/2017 — see separate entry below). This LC affidavit filed 04/04/2025 (~9 months before the Gude deed) is therefore likely a supplemental Affidavit of Successor Trustee or Affidavit of Trust Facts filed to support the upcoming Gude conveyance rather than the appointment instrument itself. Pull to confirm scope and content. Legal name confirmed as Donald Fredrick Willis Jr. (confirmed by landowner 2026-03-09). |
| — | Effective 2017-05-01; notarized 2017-10-24 | Doc ref: ;04439793 DOC/1 | TRUSTEE RESIGNATION AND APPOINTMENT OF SUCCESSOR TRUSTEE | BEARD M STEPHEN (resigning) → WILLIS D FRED (appointed) | — | **PRIVATE — UNRECORDED** | N/A (not filed in either county) | **Identified 2026-03-30**. Private document marked "Successor Trustee Copy." M. Stephen Beard resigns as Trust No. 1 trustee; D. Fred Willis appointed successor pursuant to Article X of the 1977 trust instrument. Signatories: M. Stephen Beard, John Marion Black, Kay Lynn Ramsey Black. Named beneficiaries: John Marion Black, Kay Lynn Ramsey Black, John Ramsey Black (individually and on behalf of Matthew Holland Black, his minor child), John Paul Black, Brittany Lachelle Black, Von Ramsey Black, Margaret Kate Black, Joel Matthew Black. Willis acceptance notarized Harris County 10/24/2017; notary: Laura R. Douglass (commission exp. 12/27/2017). ⚠️ This instrument has NOT been recorded in Freestone or Limestone County — recording is still required (see ISSUE-03). Willis name form in this instrument: "D. Fred Willis." |

| [309] | John T. Black (affiant) → Public (re: W.J. Needham estate) | Limestone | ✓ | LC Pg. 466–467, Doc# 1148 (pull list cited Vol. 447 — volume not confirmed in instrument text). Filed Mar 4, 1958 at 8:00 AM; recorded Mar 5, 1958 at 4:00 PM; John Kidd, County Clerk; Lila Johnson, Deputy; Limestone County. | 466–467 (2 pages) | 1958-02-15 | 1958-03-05 | **Affidavit of Heirship and Marital History** — NON-PROJECT PROPERTY. JT Black attests to W.J. Needham family's ownership of a lot in the town of Tehuacana (east end of south half of Block 23, bounded east by South First Street, south by Wade Street) since 1921. W.J. Needham (= Will J. Needham) died 1952; married once to Mary Ellen Needham; two children: one girl (died in childhood), one boy Virgil Needham (2631 E. 35th Street, Tulsa, Oklahoma). No will, no administration. No conveyance; no Black/Bounds chain impact. ⚠️ SIGNATURE DISCREPANCY: body and notarial say "John T. Black" but signature reads "John R. Black." Notary: Mary Cogdell, Limestone County. ISSUE-43 item 10. |
| [310] | L.L. Dorsett and wife Genevieve B. Dorsett → Mrs. H.O. Eady | Limestone | ✓ | LC Vol. 457, Pg. 598–599, Inst# 05901309. Filed Feb 23, 1959 at 3:00 PM; recorded Feb 25, 1959 at 4:00 PM; John Kidd, County Clerk; Lila Johnson, Deputy; Limestone County. | 598–599 (2 pages) | 1959-01-13 | 1959-02-25 | **Warranty deed** — NON-PROJECT PROPERTY. L.L. Dorsett and wife Mrs. Genevieve B Dorsett (Limestone County) convey lot at SE corner of south half of Block 23, Town of Tehuacana, to Mrs. H.O. Eady (Limestone County). Beginning at SE corner of Block 23, west 50 feet, north full length to alley, east to east line of Block 23, south to beginning. Consideration: $5,500 cash. Full warranty deed — surface + minerals, no reservations. Signed at Tyler, Texas; joint acknowledgment before Edd Oliver, Notary Public, Smith County, Texas, Jan 13, 1959. Genevieve B. Dorsett examined privily and apart from husband. Documentary stamps: $5.00 + $1.00 + $0.05 = $6.05. **Block 23 connection**: Same block as deed [309] Needham heirship affidavit — Dorsett lot (SE corner, south half) and Needham lot (east end, south half) are adjacent or overlapping parcels. No Black/Bounds chain impact. Confirms L.L. Dorsett identity from instrument text (corroborates deed [312] identification). ISSUE-43 item 16. Phase: N/A (non-project property) |
| [312] | Kelly Bounds + Jeff Bounds (affiants) → Public (re: John T. Black estate heirship) | Limestone | ✓ | LC Vol. 458, Pg. 317, Inst# 05901580. Filed Mar 9, 1959 at 10:00 AM; recorded Mar 11, 1959 at 4:00 PM; John Kidd, County Clerk; Lila Johnson, Deputy; Limestone County. | 317–318 (2 pages) | 1959-02-09 | 1959-03-11 | **Affidavit of Heirship** — Boyd Survey upstream chain. Affiants Kelly Bounds and Jeff Bounds (Bounds family members, each over 21, personally acquainted with JT Black during his lifetime) attest: JT Black died intestate 1/30/1959; married once only to Verona E. Pierce (and she married once only to JT Black); three children: (1) J. P. Black, son, Limestone Co.; (2) Georgia Nell Black m. R. A. Ennis, Harris Co.; (3) Genevieve Black m. L. L. Dorsett, Dallas Co.; no adoptions; no administration pending; estate appraised < $10,000; "John T. Black and J. T. Black are one and the same person and name." Execution date: Feb 9, 1959 (10 days after JT Black's death). Sworn/acknowledged Feb 24, 1959 before Mary Cogdell, Notary Public, Limestone County (same notary as deed [309]). Companion instrument to ISSUE-43 item 2 (gift deed, JP et al → Verona, LC Vol. 458 Pg. 314, Inst# 05901581, same-day filing). **NEW IDENTIFICATIONS**: L. L. Dorsett (Genevieve's husband — previously unknown); R. A. Ennis (Georgia Nell's husband — previously unknown). Phase 2 upstream documentation. ISSUE-43 item 3. |
| [311] | J. P. Black, Georgia Nell Ennis (+ R. A. Ennis), Genevieve Dorsett (+ L. L. Dorsett) → Verona E. Black | Limestone | ✓ | LC Vol. 458, Pg. 314, Inst# 05901581. Filed Mar 9, 1959 at 10:00 AM; recorded Mar 11, 1959 at 4:00 PM; John Kidd, County Clerk; Lila Johnson, Deputy; Limestone County. | 314–316 (3 pages) | 1959-02-09 | 1959-03-11 | **Gift deed** — Boyd Survey upstream chain (JT Black estate consolidation). Grantors: J. P. Black (Limestone Co.), Georgia Nell Ennis and husband R. A. Ennis (Harris Co.), Genevieve Dorsett and husband L. L. Dorsett (Dallas Co.). Grantee: Verona E. Black (Limestone Co.), mother of grantors. Consideration: love and affection. Property: "all of our interest in the estate of John T. Black, deceased, including all real and personal property of every kind and character, whether situated in Limestone County, Texas, or any other county or state" — blanket conveyance, not limited to Boyd Survey. No mineral reservation — full fee simple. Habendum: to Verona, her heirs and assigns forever. Acknowledgments: all three sets of grantors acknowledged Feb 21, 1959 in Limestone County (despite Ennis in Harris Co., Dorsetts in Dallas Co.); Georgia Nell Ennis and Genevieve Dorsett each examined privily and apart from husband; notary names illegible, seals embossed. Companion instrument to deed [312] (heirship affidavit, Pg. 317, same-day filing). **Establishes upstream chain for deed [24]**: JT Black (d. 1/30/1959) → heirs by intestacy → [311] gift deed → Verona E. Black (100%) → [24] (1974). ISSUE-43 item 2. Phase 2 |
| [314] | W. D. Bounds + Jeff Bounds (affiants) → Public (re: Verona E. Black title, 56.8 ac Lipscomb Norvell Survey) | Limestone | ✓ | LC Vol. 516, Pg. 304–305, Doc# 3773. Filed Jul 26, 1965 at 10:00 AM; recorded Jul 26, 1965 at 4:00 PM; John Kidd, County Clerk; Eleanor Popejoy, Deputy; Limestone County. | 304–305 (2 pages) | 1965-06-08 | 1965-07-26 | **Affidavit of Title** — DISPOSED PROPERTY (Norvell Survey). Affiants W.D. Bounds and Jeff Bounds (each over 21, personally acquainted with the property) attest: 56.8 ac Lipscomb Norvell Survey, Abstract No. 20, LC. Metes-and-bounds: beginning at T.W. Wade's SW corner in south line of 400-ac survey bought by John Caruthers from Lipscomb Norvell; S 430 vrs; E 745-8/10 vrs to Jones NE corner; N 430 vrs; W 745-8/10 vrs to POB. Chain: W.E. Black + wife Ida A. Black acquired >40 years before 1965; W.E. Black and his children conveyed to J.T. Black in 1943; JT Black died 1959; children conveyed to Verona E. Black (= deed [311] blanket conveyance). Adverse possession attested: 40+ years continuous, fenced (capable of turning cattle), notorious, peaceable, uninterrupted. No oil, gas, or mineral production. Attorneys: Schultz & Martin, Mexia TX. Sworn Jun 8, 1965; subscribed/acknowledged Jun 9, 1965 before E. B. Trotter NP, Limestone County. **Companion to deed [316] (Wilson deed) at LC Vol. 516 Pg. 307 (PULLED ✓ 2026-03-31)** — Verona sold this tract to Wilson in 1965. Vol. 516 from ISSUE-43 item 9 index identification. ISSUE-43 item 9 (pg. 304 portion). Phase 2 |
| [316] | Verona E. Black (widow) → Mary Rees Wilson (widow, Norman OK) | Limestone | ✓ | LC Vol. 516, Pg. 307–308, Doc# 3775. Filed Jul 26, 1965 at 10:00 AM; recorded Jul 28, 1965 at 4:00 PM; John Kidd, County Clerk; Eleanor Popejoy, Deputy; Limestone County. | 307–308 (2 pages) | 1965-06-08 | 1965-07-28 | **Warranty Deed** — DISPOSED PROPERTY (Norvell Survey). 56.8 ac Lipscomb Norvell Survey, Abstract No. 20, LC. Metes-and-bounds identical to [314] affidavit. Surface + ALL minerals conveyed (explicit: "Grantor herein hereby conveys to grantee herein all of the oil, gas and other minerals in, to and under said above described land"). Consideration: $10.00 + OGVC; documentary stamps $4.95 (4×$1.10 + 1×$0.55; implied actual consideration ~$4,001–$4,500 per 1965 federal stamp rate of $0.55/$500). General warranty deed — warrant and forever defend. Grantee residence: City of Norman, State of Oklahoma. Acknowledged Jun 9, 1965 before Joe Schultz NP, Limestone County (same attorney firm as [314]: Schultz & Martin, Mexia TX; Joe Schultz is the notary on both instruments). Companion to [314] affidavit (Pg. 304, Doc# 3773, same-day filing Jul 26, 1965). **Completes Norvell Survey disposition chain**: W.E. Black + Ida A. Black (pre-~1925) → JT Black (1943) → heirs by intestacy → Verona E. Black (1959, [311]) → Mary Rees Wilson (1965, [316]). Property permanently left family chain. ISSUE-43 item 9 (pg. 307 portion). Phase 2 |
*Add rows as additional PDFs are reviewed.*

**Note on [05]/[23] dual-county filing**: These are the same instrument. Limestone County filed and recorded first (Oct 10–13, 1972). Freestone County filed second (Oct 24 – Nov 1, 1972) using the Limestone County official copy (stamps 6178/3032 visible on Freestone filing).

### Outstanding Recording Citations (text files only — not yet confirmed from PDFs)

Deeds [101], [105]: Filing/recording dates added from deed source file text (Session 5). Volume/page citations not stated in source text for [105]; [101] Vol/Pg confirmed only from [105] cross-reference. Both require verification from Limestone County deed records. Deed [109]: [Page 514] per margin note; filing/recording dates from source text; recording date anomaly documented (ISSUE-39). **County Deed Index Session (2026-03-08)**: LC index confirmed Vol/Pg for deeds [111] (Vol. 51 Pg. 537), [104] (Vol. 2 Pg. 528), [113] (Vol. 63 Pg. 167), [114] (Vol. 63 Pg. 405), [115] (LC Vol. 233 Pg. 136; FC DR/128/18), [118] (Vol. 469 Pg. 280). FC index confirmed citations for deeds [14] (OR/1327/554), [15] (OR/1327/568), [16] (OR/1327/561), [17] (OR/1327/571), [20] (OR/1327/579). Deed [107] probable match at LC Vol. 32 Pg. 62 — date discrepancy requires verification. Deed [108] Vol. S Pg. 582 confirmed but grantee name discrepancy (T.W. vs J.W.) flagged. Deeds [110], [117] not found in Bounds surname index — require searches under grantor surnames (Smith, Federal Land Bank). **Mallard/Longbotham/Lindley/Lee session (2026-03-09)**: Deed [102] confirmed at LC Book O Pg.554 (Mallard index); deed [103] confirmed at LC Book O Pg.553 (Longbotham index); deed [105] confirmed at LC Vol.2 Pg.383 (Lindley index). Deed [109] NOT found in Lee index — systematic gap for 1890-era R.E. Lee grantee entries; volume for [109] remains unresolved (page 514 known from margin note). Deed [101] NOT found in Lindley index — likely indexed under "KINDLEY" (granting clause spelling); recommend K-Kindley search or direct courthouse pull at Book M pp.390-392. New instrument identified: [125] Lindley→Lee 30 ac Holloway Survey (LC Vol.8 Pg.512, 1890). Deed [106]: Haley surname search completed 2026-03-09 — probable match at LC Vol. 2 Pg. 381 (Inst# DR-00002-00381, "HALEY K H" → BOUNDS J H); grantor name discrepancy ("K H" vs "Hiram") prevents confirmed status; verification pull needed. Deed [116] Vol. 252 Pg. 463 validated. **Smith surname session (2026-03-09)**: Deed [110] CONFIRMED at LC Book 8 Pg. 595 (Inst# DR-00008-00595, SMITH A M + → BOUNDS J H, S MC ANULTY HRS, 9 1/8 ACRES, 05/24/1890). Index recorded date = filing date (05/24/1890), consistent with 1890-era index behavior. New McAnulty/Bounds instrument identified: SMITH A H + → BOUNDS S T, 345 ac McAnulty (LC Book 26, Pg 15, Inst# DR-00026-00015, 08/12/1897) — S T Bounds identity unknown; flagged in ISSUE-34. Additional instrument flagged: SMITH A M + → BENNETT E G (LC Book 14, Pg 121, Inst# DR-00014-00121, 10/27/1892, MULTIPLE PROPERTIES) — potential Bennett family cross-transaction; no deed number assigned. Bennett heir chain (Targets C–E) not searchable from Smith index — requires Bennett surname search. Deed [117] (Federal Land Bank) still requires separate surname search.
**County Deed Index Session (2026-03-09)**: FC Ballard surname search (493 records) — no record found at DR/31/182 (C.C. Ballard et ux, 1908). Result is NON-PROBATIVE: earliest Ballard-surname FC index record is from 1934 (DR/131 range); the 1908 target predates coverage by ~26 years. Citation FC Vol. 31 p.182 remains PDF-verified by landowner; no concern raised. LC Haley surname search (146 records) — deed [106] probable match found (see deed register entry above).

### Notes for App Development
- Store both the PDF (as a file reference or blob) and the transcribed text for each deed
- Flag any deed where PDF has not been reviewed against the transcription
- Recording citation fields (volume, page, filed date, recorded date, county clerk) should be populated from PDF review, not from transcription

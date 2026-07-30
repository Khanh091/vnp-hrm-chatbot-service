# Profile data trace report

Date: 2026-07-30  
Database: `hrm`

## Source of truth and resolved subject

The employee self-declaration form uses `vnpt.hr.employee.edition`.
`vnpt.hr.employee.edition.action_confirmed()` copies approved changed fields
to `hr.employee`, marks the edition `confirmed`, updates confirmed child
records, and retains the link through `hr.employee.employee_edition_id`.
Subsequent writes on `hr.employee` are synchronized back to the linked
edition by `vnpt_hr_profile/models/hr_employee.py`.

Therefore:

- draft/waiting self-declared data: `vnpt.hr.employee.edition`;
- approved operational profile used by chatbot business APIs: `hr.employee`;
- retained approval/audit record: linked `vnpt.hr.employee.edition`;
- user relationship: `res.users.id -> hr.employee.user_id`, constrained to
  the user's current company by `UserContextService`.

The traced actor resolves to:

| Field | Result |
|---|---|
| `odoo_user_id` | `92734` |
| `linked_employee_id` | `64247` |
| employee code | `00234086` |
| full name | `LÒ VĂN ĐỊNH` |
| employee state | `confirmed` |
| profile record model | `vnpt.hr.employee.edition` |
| profile record id | `254` |
| profile state | `confirmed` |

The self API therefore resolves the expected employee/profile pair.
No `sudo()` is used by the chatbot business query.

## Party/union

### Trace

| Stage | Before | After |
|---|---|---|
| Source model | Approved fields on `hr.employee`; party history in `vnpt.hr.quatrinhsinhhoatdang` | unchanged |
| Source fields | `vnpt_la_dang_vien_ok`, `so_the_dang`, `ngay_cap_the`, `dangbo_cap_the`, `vnpt_ngay_vao_dang`, `ngaychinhthucvaodang`, party organization fields | unchanged |
| Odoo service | Queried `vnpt.hr.quatrinhsinhhoatdoan` only | Queries party and union history independently |
| Odoo mapper | Returned membership boolean, join date, union fields only | Returns card metadata, probationary/official dates, organization, `party_history`, and union data |
| Odoo JSON | `is_party_member=true` was already present | All approved party fields are present |
| FastAPI client | Preserved `true` | unchanged |
| `ToolExecutionResult` | Preserved `true` | unchanged |
| Sanitizer | Preserved `is_party_member` and `false` union membership | unchanged |
| Final context | Would preserve party keys if the party tool ran | safe key/size logging added |
| Live routing | Selected `profile_get_summary`, so party data never reached final answer | exclusive semantic concept selects `profile_get_party_union` |

The card number exists in the response but is not copied into diagnostic
logs or this report.

### Root cause

The observed “not stored” answer was primarily a routing failure in the
running FastAPI image: it executed `profile_get_summary`. The Odoo mapper was
also incomplete for detailed party questions and queried union history for
the party capability.

## Education

### Trace

| Stage | Before | After |
|---|---|---|
| Source model | Summary on `hr.employee`; history in `vnpt.hr.trinhdohocvan` | unchanged |
| Source fields | `datotnghieplop_id`, `hetotnghiep`, `vnpt_trinhdodaotao_id`, `hinhthuc_daotao`, `vnpt_chuyen_nganh_dao_tao`, `vnpt_ngay_tot_nghiep`, `vnpt_noi_dao_tao`, `lyluanchinhtri` | unchanged |
| Odoo service | Returned only `education[]` child records | Combines employee summary and professional records |
| Odoo JSON | Initial trace returned `{"education":[]}` | Returns `general_education`, `education_system`, `highest_professional_level`, `training_form`, `major`, `graduation_year`, `institution`, `political_theory_level`, and records |
| FastAPI client/result | Did not remove keys; the keys were absent upstream | preserves all new keys |
| Sanitizer | Preserves education business keys | unchanged |
| Final context | Previously received only an empty collection | receives summary plus records |
| Final answer | Correctly concluded no data from the incomplete DATA | can answer the requested education field |

### Root cause

Data was lost in `ProfileService._education()`: it queried only the
one-to-many table and ignored summary fields displayed directly on the
approved employee/profile. This is fixed in the Odoo service/mapper rather
than in the prompt.

## Address

### Trace

| Stage | Result |
|---|---|
| Source model | Approved address fields on `hr.employee` |
| Source fields | `noiohiennay_tinh_thanhpho_id`, `noiohiennay_quan_huyen_id`, `noiohiennay_xa_phuong_id`, `noiohiennay_thon_xom` |
| Odoo mapper | Builds an address from any populated component; detail is not required |
| Odoo JSON | `current_address` contains province, ward, null detail, and a complete `full_address` |
| FastAPI client/result | Nested object preserved |
| Sanitizer | `current_address`, `province`, and `ward` preserved |
| Live routing | Incorrectly selected `profile_get_contact` |
| After fix | exclusive “current address/hometown” concept selects `profile_get_addresses` |

### Root cause

No address data was lost in Odoo or the sanitizer. The running FastAPI image
executed the wrong tool, so the final model received contact data instead of
address data.

## Null, false, and empty collections

- `is_party_member=false` remains `false`; it is not converted with
  `value or None`.
- `null` remains unknown/not stored.
- `[]` remains an existing empty collection.
- The FastAPI client and sanitizer do not use truthiness filtering and
  preserve `false`, `0`, nested objects, and empty lists.

## Verification

The source-new Odoo instance was first verified temporarily on port 8071.
The normal Odoo process on port 8069 was then restarted and the same
production-facing endpoints were verified again. They returned:

- party: `is_party_member=true`, all card/join/organization fields, and one
  party-history item;
- education: `12/12`, `THPT`, `Đại học`, `Chính quy`, the configured major,
  graduation year 2027, institution, and one professional record;
- address: a current-address object built from ward and province despite a
  null detail.

FastAPI targeted trace tests cover eight queries and record:
classification, selected tool, registered endpoint, raw business keys,
sanitized keys, and deterministic final answer.

The FastAPI Docker image was rebuilt and the eight live requests all returned
`answer` with the expected tool:

| Query concept | Selected tool | Live result |
|---|---|---|
| Party membership | `profile_get_party_union` | member is recorded |
| Party card number | `profile_get_party_union` | card number returned |
| General education | `profile_get_education` | `12/12`, `THPT` |
| Professional training | `profile_get_education` | degree/form/major/institution returned |
| Major | `profile_get_education` | major returned |
| Institution | `profile_get_education` | institution returned |
| Current address | `profile_get_addresses` | ward and province returned |
| Hometown | `profile_get_addresses` | correctly reports the source field is empty |

Observed live end-to-end latency was approximately 1.47–1.90 seconds per
request. No production value is hardcoded in routing, mapper, sanitizer, or
fallback code.

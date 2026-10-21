# THREATS.md
Format per entry: Threat | Mitigation | Test | Status

## Authentication & sessions (step 2)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| Credential stuffing / brute force | argon2 hashing, per-account lockout (5 fails / 15 min) | test_lockout_blocks_even_the_correct_password | Closed: per-account lockout plus a per-IP limit (in-process, see accepted note below) |
| Account lockout used as a DoS on a victim | Accepted: lockout is time-limited; attacker can keep a known email locked | - | Accepted |
| User enumeration via login | Same message and similar timing for unknown user vs wrong password (dummy hash) | test_wrong_password_and_unknown_user_look_identical | Closed (timing is best-effort) |
| Stolen DB leaks sessions | Only SHA-256 of session token stored | test_passwords_and_tokens_are_not_stored_in_plaintext | Closed |
| Session still works after logout / deactivation / password change | Session + user row re-checked in DB every request | test_logout_kills_token_immediately, test_deactivating_user_kills_existing_session_immediately, test_password_change_revokes_other_sessions | Closed |
| CSRF on cookie sessions | SameSite=Strict + Origin/Referer check on cookie-authenticated writes | test_csrf_cross_origin_cookie_request_is_blocked | Closed |
| Role escalation via admin routes | require_roles on every /admin route, denials audited | test_roles_are_enforced_on_admin_routes | Closed |
| Last admin locks themselves out | Admins cannot demote/deactivate themselves | test_admin_cannot_demote_or_deactivate_self | Closed |
| Audit tampering | Hash chain, Postgres triggers, insert-only DB role | test_audit_chain_verifies_and_detects_tampering, test_audit_deletion_in_the_middle_is_detected | Closed except tail truncation: needs head hash kept outside the system (accepted, documented) |

## Documents, storage, authorisation (step 3)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| IDOR: guess/enumerate another user's document id | Every document route calls `authorize()`; grant read from DB each request | test_ungranted_user_cannot_reach_document_by_any_route | Closed |
| Existence leak (403 vs 404, timing of lookups) | No access, unknown id and non-UUID id all return the identical 404 body | test_refusal_is_identical_to_nonexistent_document | Closed (timing not measured) |
| Reaching a document through a *different* route (list, search, versions, download) | Search runs inside the user's accessible set; version lookup bound to the document id | test_list_and_search_never_include_other_peoples_documents, test_cannot_download_another_documents_version_through_my_document | Closed |
| Version-id IDOR (my doc id + someone else's version id) | Query filters on both `document_id` and `version id` | same as above | Closed |
| Admin as a super-reader | Admin role gets no content access, even with a grant row or ownership | test_admin_can_not_read_content_but_sees_metadata, test_admin_with_a_grant_row_still_gets_nothing | Closed (design decision; costs: admins cannot help a user recover a file) |
| Viewer given edit through direct DB/grant bug | Effective permission capped to `read` for role viewer at check time | test_viewer_role_is_capped_at_read_even_with_edit_grant_row | Closed |
| Ex-owner keeps powers after demotion | Ownership only counts when role is still `owner` | test_owner_demoted_to_viewer_loses_ownership_powers | Closed |
| Expired grant keeps working | Expiry compared at every request | test_expired_grant_gives_nothing | Closed |
| Revocation not immediate | Grants deleted; nothing cached; no long-lived download links | test_revoking_a_grant_takes_effect_on_the_very_next_request | Closed, except a download already streaming when access is removed finishes (accepted) |
| Path traversal / filename tricks | Disk name is a random 128-bit key; strict regex + resolved-path check; client name sanitised, used only in headers | test_stored_filename_is_random_and_user_filename_never_touches_disk | Closed |
| Stored XSS via uploaded HTML/SVG | Allowlist excludes html/svg; downloads are `attachment` + nosniff + CSP sandbox | test_bad_uploads_are_rejected, test_download_headers_force_attachment_and_block_sniffing | Closed |
| Extension/content mismatch, polyglots | Extension allowlist AND signature check; server picks mime type | test_bad_uploads_are_rejected | Closed for listed types (not a malware scanner: accepted) |
| Zip bomb inside docx/xlsx/pptx | Entry-name check, total expanded size and ratio caps | test_zip_bomb_is_rejected | Closed |
| Oversized upload / disk exhaustion | Early Content-Length guard + cap on bytes actually read | test_oversized_upload_is_rejected_both_early_and_by_bytes_read | Partly: chunked uploads without Content-Length are only capped when read; needs a proxy limit in production (accepted) |
| Search wildcard abuse (`%`, `_`) | LIKE patterns auto-escaped | test_search_wildcards_are_literal | Closed |
| Refused attempts invisible afterwards | Every refusal committed to the audit log before the error is raised | test_refused_attempts_are_audited_with_actor_and_document | Closed |
| Files readable by anyone with disk/host access | Stored outside web root, mode 0600; NOT encrypted at rest | - | Accepted: no encryption at rest in this version |
| Deleted documents | Soft delete keeps file and history; no purge/retention job | test_soft_deleted_document_is_unreachable_but_file_is_retained | Accepted: no recovery UI or retention policy built |
| Download audited before bytes are sent | A client abort still shows as a download attempt | - | Accepted: logging intent is safer than logging completion |

## Granting and revoking (step 4)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| Stranger grants themselves (or a friend) access | All grant routes call `authorize(need='owner')`; no access gives 404 | test_stranger_cannot_grant_anything_including_to_themselves | Closed |
| Privilege escalation chain: a read/edit grantee hands access to others or edits/revokes grants | Grant management is owner-only, not delegable | test_read_or_edit_grantee_cannot_hand_out_access, test_grantee_cannot_revoke_or_downgrade_others | Closed (design choice: no delegated sharing) |
| Revoking grant X on my document actually deletes grant X on someone else's | Revoke query filtered by grant id AND document id | test_revoke_cannot_target_a_grant_on_someone_elses_document | Closed |
| Revocation lag | Revoke deletes the row; every request re-reads grants; nothing cached | test_revoke_is_immediate_on_every_route | Closed (in-flight download finishes: accepted) |
| Grant edit to viewer role, or to admin | Rejected at grant time AND capped at check time | test_viewers_cannot_be_given_edit, test_cannot_grant_to_admin_unknown_inactive_or_self... | Closed |
| Owner uses grant form to enumerate users/admins | One identical 422 for unknown, inactive, admin and self | same test | Closed |
| Permanent access forgotten | Optional expiry (max 365 days) checked on every request | test_expiry_rules | Partly: expiry is optional, no mandatory review/re-certification (accepted) |
| Permission changes not provable afterwards | grant_create / grant_update (with before and after) / grant_revoke / refused attempts all audited | test_update_changes_level_and_is_audited..., test_permission_changes_are_visible_to_admin... | Closed |
| Re-granting resurrects an old grant id | Revoke deletes; re-grant makes a new row and id | test_regrant_after_revoke_creates_a_fresh_grant | Closed |
| Owner leaves company / owner account compromised | Owner deactivation kills sessions, but docs stay owned by them; no ownership transfer | - | Accepted: ownership transfer not built |
| Copying: a granted reader downloads and shares the file elsewhere | Cannot be prevented by software; audit proves who downloaded and when | - | Accepted (inherent) |

## Admin activity view and alerts (step 5)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| Non-admin reads the audit log / timeline / alerts (they reveal who touches what) | Every `/admin/*` route requires role admin; refusals are themselves audited | test_only_admin_can_see_any_activity_view | Closed |
| Admin view leaks document contents | Timeline and document list return metadata only; no storage keys, no bytes | test_timeline_answers_who_opened_it_and_when_including_refused | Closed |
| Can't answer "who opened this, and when?" after a leak | Per-document timeline lists readers (count, first, last) and every refused attempt, oldest first | same test | Closed |
| History altered to hide a leak | Chain verified inside the alert run; a break is a critical alert, sorted first | test_tampered_audit_log_is_critical_and_sorted_first | Closed except tail truncation (accepted, see audit entry) |
| Slow probing / scraping goes unnoticed | Rules: repeated denials, probing many documents, mass and bulk downloads, failed logins by account and by IP, retry after revoke, grant-download-revoke, admin-area probing | test_repeated_denials_alert ... test_admin_endpoint_probing_alert | Partly: fixed thresholds in one window; a patient attacker staying under them is not flagged (accepted) |
| Alerts used as a blocking mechanism by mistake | Alerts only inform; nothing is blocked or granted automatically | - | By design |
| Admin abuses own power (create admin, deactivate users) | Account changes appear as `account_change` info alerts and in the audit log | test_account_changes_are_reported_as_info | Partly: a malicious admin can create another admin; no two-person approval (accepted) |
| Audit view becomes slow / DoS | Result limits (max 500), alert window capped at 30 days and 50k rows | test_alert_window_is_respected | Partly: alerts recompute on each call, no caching (accepted) |
| IP of clients wrong behind a proxy | `client_ip` uses the socket peer; behind Render this is the proxy | - | Accepted/open: per-IP rules are weak until forwarded headers are trusted safely |

## AI sharing suggestions (step 6)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| The machine widens access on its own | `POST .../suggestions` only stores a proposal; grants happen only in `/decisions`, on an explicit owner request. No auto-accept option exists and unknown body fields are rejected | test_suggesting_grants_nothing, test_no_auto_accept_switches_exist | Closed |
| Suggestion is used as a backdoor to grant anyone | A decision can only name a person who was in that suggestion, each candidate once; acceptance runs through the same `apply_grant()` checks as a typed grant (no admins, no inactive, viewers read-only, expiry rules) | test_cannot_use_decisions_to_grant_someone_who_was_not_suggested, test_human_choice_still_passes_normal_grant_rules | Closed |
| Hostile or hallucinated model output (made-up ids, admins, `edit` permission) | LLM may only reorder the rule-based shortlist; unknown ids dropped; permission is always `read`; failures fall back to rules | test_hostile_llm_output_cannot_add_people_or_change_permission, test_llm_failure_or_garbage_falls_back_to_rules | Closed |
| Prompt injection through document name/description | Those fields are marked untrusted in the prompt, AND the design means even a fully obeyed injection can only reorder an already-limited list that a human then confirms | test_prompt_injection_in_description_still_grants_nothing | Closed by design (injection can still skew the ordering or wording of reasons: accepted) |
| Leaking contents or the user directory to a third party | Only name, category, description and signal text are sent; never file bytes, never emails; candidates only come from the owner's own sharing history | test_only_metadata_is_sent_to_the_model_never_contents_or_emails | Partly: the document title and description do leave the system when the LLM provider is enabled (accepted; off by default) |
| Suggestion used to enumerate all users | Only people the owner has already shared with can appear (max 10) | test_candidates_come_from_owners_history_and_are_ranked_least_privilege | Closed |
| Stale suggestion confirmed after circumstances changed | 24 h expiry; grantee state re-checked at decision time | test_stale_suggestions_expire, test_candidate_deactivated_before_decision_cannot_be_granted | Closed |
| Suggestion endpoint abused for cost or noise | 20 per user per hour (429) | test_suggestion_requests_are_rate_limited | Closed |
| No record of what the AI proposed and what the human chose | `ai_suggestion` (candidates + scores + source) and `ai_suggestion_decision` (accepted / rejected) rows, plus the normal grant rows tagged `via: ai_suggestion` | test_suggestion_and_human_decisions_are_both_audited | Closed |
| Someone else reads or decides my suggestion | Owner-only; suggestion id bound to document and requester | test_only_the_owner_can_request_or_see_or_decide, test_suggestion_id_from_another_document_does_not_work | Closed |
| "Human confirms" is just an API call a script could make | The owner's authenticated session is the confirmation; there is no separate in-person/MFA step | - | Accepted: no step-up authentication |
| Live LLM path not exercised in CI | `llm_rerank` is tested only through a fake; the real HTTP call to the provider is untested here | - | Accepted: verify with a real key before relying on it |

## Web front-end (step 7)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| Stored XSS through document names, descriptions, emails or audit details | The UI builds the page with `createElement` and text nodes only; no HTML-string APIs exist in the code; strict CSP forbids inline script and third-party origins | test_javascript_never_builds_html_from_strings_or_stores_sessions, test_index_html_has_no_inline_script_style_or_handlers, UI smoke test (document named `<img src=x onerror=...>` renders as text) | Closed |
| Session theft from page scripts | Session is an HttpOnly, SameSite=Strict cookie; the UI never sees or stores a token (no localStorage/sessionStorage) | same JS test, test_cookie_is_httponly_and_samesite_strict | Closed |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every response | test_root_serves_the_app_with_strict_headers | Closed |
| Malicious script from a CDN | No third-party scripts, styles or fonts at all; CSP `default-src 'self'` | test_index_html_has_no_inline_script_style_or_handlers | Closed (the `/docs` page is the one deliberate exception: it loads Swagger from a CDN under its own relaxed CSP) |
| Hiding a button is mistaken for security | Every screen is re-enforced by the server; UI test opens an ungranted document by exact URL and gets "Not found" | UI smoke test "Server-side enforcement seen from the UI" | Closed |
| Path traversal through static files | Starlette static handler; explicit tests with encoded and raw `..` | test_static_files_are_served_and_directory_traversal_is_blocked | Closed |
| Refused download navigates browser to a raw error page / leaks details | Downloads go through `fetch`; failures show a toast, 401 returns to the login screen | UI smoke test | Closed |
| Public demo password shipped in the JavaScript | Removed: no demo credentials exist anywhere in the shipped app; sample data is development-only and needs an explicit `--demo` flag | test_no_demo_credentials_or_demo_login_shortcuts_ship_in_the_app, test_seed_script_refuses_to_run_without_an_explicit_development_flag | Closed |
| UI correctness in real browsers | Tested in jsdom only | - | Accepted: manual check in a real browser still needed |

## Real accounts, Google sign-in, approvals, document review (step 8)
| Threat | Mitigation | Test | Status |
|---|---|---|---|
| Someone makes themselves an administrator | Registration only accepts `owner`/`viewer`; no endpoint creates admins except an existing admin; the first admin comes from `ADMIN_EMAIL`/`ADMIN_PASSWORD`; Google may create an admin only for allow-listed emails | test_nobody_can_self_register_as_admin_and_input_is_validated, test_google_cannot_create_administrators_unless_allow_listed, test_first_admin_is_created_from_the_environment_once | Closed |
| An unapproved (pending) account does something | Default-deny: `current_user` requires `active`; only `/auth/me` and `/auth/logout` use the looser dependency | test_pending_account_cannot_do_anything_else, test_new_account_starts_pending_and_can_only_see_its_own_status | Closed |
| Approval, rejection or suspension does not bite immediately | Status is re-read from the database on every request; reject/suspend revoke all sessions | test_approval_takes_effect_immediately_on_the_same_session, test_rejection_blocks_login_with_the_reason_and_kills_the_session, test_suspend_and_reactivate | Closed |
| Forged, wrong-audience, wrong-issuer or unverified Google token | Verified server-side: signature, audience = our client id, issuer, expiry, `email_verified` | test_real_verifier_checks_audience_issuer_and_email_verified, test_bad_google_token_is_refused_and_audited | Closed. Not covered: replay of a still-valid ID token (needs a nonce); accepted, the token only ever creates a normal session |
| Pre-registering a victim's email to take over their Google login | A Google sign-in for an email that already has a password account takes the account over: password destroyed, sessions revoked, audited | test_google_takes_over_an_unverified_password_account_with_the_same_email | Closed |
| Wrong portal / role confusion | Portal must match the role, checked only after the password or Google proof (no role leak to strangers) | test_portal_must_match_the_account_role, test_google_respects_rejection_and_portal | Closed |
| Account status leaked to someone without the password | "Declined/suspended" is only revealed after a correct password | test_rejection_blocks_login_with_the_reason_and_kills_the_session | Closed |
| Sign-up spam / farming accounts | Admin approval gate, per-IP limit (10/hour), `signup_burst` alert | test_registration_and_login_are_rate_limited_per_address, test_signup_burst_raises_an_alert | Partly: limits are per process (accepted); duplicate-email answer (409) lets someone check whether an email is registered (accepted) |
| Password sign-ups use someone else's email | Admin sees "Email not verified" next to the request and decides | UI smoke test | Accepted: no confirmation-link flow yet |
| Content changed after the admin approved it | A new version (upload or in-browser edit) voids the approval; the old content is no longer reachable by others | test_a_new_version_voids_the_approval, test_an_editor_grantee_also_cannot_slip_unreviewed_content_past_the_admin | Closed |
| Unapproved or rejected document reachable by others | Authorisation requires `approved`; sharing is refused until approved; rejection cuts off existing readers at once | test_new_uploads_wait_for_review_and_nobody_else_can_reach_them, test_rejection_needs_a_reason_blocks_sharing_and_cuts_off_existing_readers_at_once | Closed |
| A suspended owner's documents stay shared | Authorisation also requires the owner to be `active` | test_suspending_an_owner_freezes_sharing_of_their_documents | Closed |
| Policy bypass (file type, size, category) | Enforced on the server for uploads, compose, text versions and renames; admin-only changes, audited with before/after | test_admin_controls_which_file_types_categories_and_sizes_may_be_uploaded, test_category_rule_also_applies_when_renaming | Closed |
| Admin approves blindly because contents are hidden | By design admins see metadata (uploader, type, size, checksum, description) only | test_admin_sees_who_uploaded_what_but_never_contents | Accepted: no content or malware scanning |
| Stored XSS in written/edited documents, names, reasons | Text is stored as a file and only ever inserted as text nodes; previews cover text, PNG and JPEG only (no SVG/HTML) | UI smoke test (hostile title and `<script>` body render literally) | Closed |
| Google script widens the CSP for everyone | Google sources are added only when `GOOGLE_CLIENT_ID` is set, only on the app page, limited to the exact `/gsi/` paths; no `unsafe-inline` | test_csp_allows_google_sign_in_only_when_configured_and_only_on_the_app_page | Closed |
| Bootstrap admin credentials | Must be set together, 10+ characters; created once; never logged; rotate by changing the password in the app | test_bootstrap_refuses_weak_or_half_configured_credentials | Partly: the password sits in an environment variable (use your host's secret store) |
| Notification emails leak data or inject headers | Built with `EmailMessage` (no header injection); bodies contain no secrets or document contents; failures swallowed | - | Accepted: SMTP delivery not exercised in tests |
| Old database from an earlier version | Startup refuses with a clear message instead of failing in odd ways | test_old_databases_get_a_clear_error_instead_of_a_crash | Closed |
| Admin created with the public placeholder password from `.env.example` | Startup refuses the placeholder email/password values and tells the operator to set their own | test_placeholder_admin_credentials_from_the_example_file_are_refused | Closed |

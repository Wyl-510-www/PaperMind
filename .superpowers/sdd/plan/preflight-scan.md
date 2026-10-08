# Preflight Scan — Phase 2 Plan

Date: 2026-10-08
Plan: specs/2026-10-07-phase-2-streamlit-ui/plan.md

## Cross-Task File Dependencies

| Tasks | Shared File/Interface | What One Produces | What Other Consumes | Finding |
|-------|----------------------|-------------------|---------------------|---------|
| TG1, TG2 | `papermind/app_service.py` | Identity, IDENTITIES, save_note interface | Used by TG2 tests and impl | Clean - TG1 defines, TG2 uses |
| TG1, TG3 | `papermind/app_service.py` | Identity, EvidenceItem, AskResult | Used by TG3 for ask_memory | Clean - TG1 defines, TG3 uses |
| TG2, TG4 | `papermind/app_service.py` | save_note, sync_notes functions | Called by Streamlit page | Clean - TG2 implements, TG4 calls |
| TG3, TG4 | `papermind/app_service.py` | ask_memory function | Called by Streamlit page | Clean - TG3 implements, TG4 calls |
| TG3 | `papermind/memory_retrieval.py` | Structured evidence adapter | Used by ask_memory | Clean - internal to TG3 |
| TG1, TG2, TG3 | `tests/test_app_service.py` | Test file | Each TG adds tests | Clean - incremental additions |
| TG4 | `streamlit_app.py`, `tests/test_streamlit_app.py` | New files | Created by TG4 | Clean - no prior tasks touch these |
| TG5 | `scripts/verify_phase2_ui.py` | New file | Created by TG5 | Clean - no prior tasks touch |
| TG1 | `pyproject.toml` | Adds streamlit dependency | Used by TG4 | Clean - TG1 adds, TG4 needs |

## Internal Task Consistency

| Task | Tests vs Code | Files Created vs Later Touched | Consistency Check |
|------|--------------|-------------------------------|-------------------|
| TG1 | Contract tests before implementation | Creates contracts, TG2/3 use them | ✅ Tests specify contracts TG2/3 need |
| TG2 | save_note tests → impl; sync_notes tests → impl | Adds to app_service.py and tests | ✅ Tests match requirements |
| TG3 | Structured retrieval tests → impl; ask_memory tests → impl | Modifies memory_retrieval.py, adds to app_service.py | ✅ Tests cover both retrieval and LLM integration |
| TG4 | Page tests → impl | Creates streamlit_app.py and tests | ✅ Tests verify UI behavior without real services |
| TG5 | Validation script → real services | Creates verify script | ✅ Script validates full stack |
| TG6 | Regression suite | No new files | ✅ Runs existing tests |

## Plan vs Spec Alignment

| Plan Requirement | Spec Section | Alignment |
|------------------|--------------|-----------|
| Three fixed identities | Requirements 2.1 item 2 | ✅ Both specify tenant_A/user_A, tenant_A/user_B, tenant_B/user_A |
| Two-step save confirmation | Requirements 3.1 | ✅ Both mandate confirmation before save_turn_to_memory |
| Status display (saved/partial/skipped/no_memory/failed) | Requirements 3.1 table | ✅ Plan matches spec states |
| Sync doesn't guarantee retrieval | Requirements 3.2 | ✅ Both state batch done ≠ current note retrievable |
| Evidence structure | Requirements 4 (EvidenceItem) | ✅ Both specify memory_id, content, type, confidence, created_at |
| No PDF/REST/auto-worker | Requirements 2.2 | ✅ Both exclude same features |
| Real services required | Requirements 1, 6 | ✅ Both mandate no mock success |

## Plan vs Global Constraints

| Global Constraint | Task Check | Finding |
|-------------------|------------|---------|
| Only P0 features | All TGs | ✅ No PDF, REST API, or P2 摘要 in any task |
| Page → service layer only | TG4 steps 2-7 | ✅ UI calls app_service functions, not DB/Qdrant directly |
| Three fixed identities | TG1 step 2, TG4 step 1 | ✅ IDENTITIES tuple enforced, page dropdown limited |
| Save requires confirmation | TG2 step 1, TG4 step 3 | ✅ confirmed=False doesn't call save_turn_to_memory |
| Query doesn't call save | TG3 step 3-4, TG4 step 5 | ✅ ask_memory only calls retrieval + LLM |
| Status distinctions | TG2 step 2, TG4 step 3-5 | ✅ All states mapped and displayed separately |
| Each save gets UUID turn_id | TG2 step 1 | ✅ Generated per save_note call |
| Real services or block | TG5 step 5, TG6 step 3 | ✅ Exit non-zero if services unavailable |

## Review Rubric vs Plan Mandates

| Review Rubric Rule | Plan Mandate | Conflict? |
|--------------------|--------------|-----------|
| No tests that assert nothing | TG1-5 all specify test assertions | ✅ No conflict - tests must verify behavior |
| No verbatim duplication | Tasks reuse Phase 1.2/1.3, don't copy | ✅ No conflict - calls existing functions |
| YAGNI - no speculative features | Plan explicitly excludes PDF, REST, etc. | ✅ No conflict - only P0 |
| Tests must be runnable | Each TG ends with pytest verification | ✅ No conflict - required |

## Conclusion

**Scan result:** Clean. No cross-task conflicts, internal inconsistencies, or plan-vs-spec/constraints contradictions detected.

All tasks follow sequential dependency order (TG1 contracts → TG2/3 use → TG4 integrates → TG5 validates → TG6 confirms). Each task's tests specify what its code must implement. Plan requirements align with spec. Global constraints enforced throughout.

**Proceed to Task Group 1.**

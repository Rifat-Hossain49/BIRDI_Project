### CorrectBench frontend

| # | stage | tasks surviving | lost here | reason |
|---|---|---:|---:|---|
| 0 | tasks requested | 156 | -- | -- |
| 1 | frontend produced a testbench | 156 | -- | -- |
| 2 | driver parsed by the adapter | 150 | 6 | driver parsed failed (6) |
| 3 | python checker loadable | 150 | -- | -- |
| 4 | Channel 1 emitted (frozen bytes) | 150 | -- | -- |
| 5 | formal toolchain available | 150 | -- | -- |
| 6 | two or more candidate families | 139 | 11 | only 1 candidate family (10); only 0 candidate family (1) |
| 7 | checker expectations recoverable | 125 | 14 | expectations unrecoverable (14) |
| 8 | state model validated vs check_dut | 108 | 17 | state model unusable (load raised: KeyError: 'a') (7); state model unusable (no comparable expectations) (5); state model unusable (load raised: KeyError: 'data0') (1); state model unusable (load raised: KeyError: 'in1') (1); state model unusable (load raised: KeyError: 'x') (1); state model unusable (direct-drive disagrees at 5/10 positio (1); state model unusable (load raised: KeyError: 'x3') (1) |
| 9 | candidate pairs submitted to BMC | 108 | -- | -- |
| 10 | BMC returned SAT (a disagreement exists) | 54 | 54 | BMC found no disagreement (UNSAT / timeout / unsupported) (54) |
| 11 | witness parsed and legal | 54 | -- | -- |
| 12 | frozen checker had an opinion | 54 | -- | -- |
| 13 | shadow tests built | 54 | -- | -- |
| 14 | safety gate passed | 17 | 37 | A. no candidate passed Channel 1 (gate had nothing to test) (21); B. shadow suite did not simulate (10); C. shadow rejects a Channel-1-passing candidate (DISCARDED DETECTION) (6) |
| 15 | Channel 2 suite shipped | 17 | -- | -- |

### AutoBench frontend

| # | stage | tasks surviving | lost here | reason |
|---|---|---:|---:|---|
| 0 | tasks requested | 156 | -- | -- |
| 1 | frontend produced a testbench | 156 | -- | -- |
| 2 | driver parsed by the adapter | 137 | 19 | driver parsed failed (19) |
| 3 | python checker loadable | 137 | -- | -- |
| 4 | Channel 1 emitted (frozen bytes) | 137 | -- | -- |
| 5 | formal toolchain available | 137 | -- | -- |
| 6 | two or more candidate families | 125 | 12 | only 1 candidate family (11); only 0 candidate family (1) |
| 7 | checker expectations recoverable | 105 | 20 | expectations unrecoverable (20) |
| 8 | state model validated vs check_dut | 52 | 53 | state model unusable (no GoldenDUT) (45); state model unusable (no comparable expectations) (3); state model unusable (direct-drive disagrees at 2/30 positio (1); state model unusable (direct-drive disagrees at 10/29 positi (1); state model unusable (direct-drive disagrees at 9/20 positio (1); state model unusable (direct-drive disagrees at 4/26 positio (1); state model unusable (direct-drive disagrees at 7/10 positio (1) |
| 9 | candidate pairs submitted to BMC | 52 | -- | -- |
| 10 | BMC returned SAT (a disagreement exists) | 26 | 26 | BMC found no disagreement (UNSAT / timeout / unsupported) (26) |
| 11 | witness parsed and legal | 26 | -- | -- |
| 12 | frozen checker had an opinion | 26 | -- | -- |
| 13 | shadow tests built | 26 | -- | -- |
| 14 | safety gate passed | 9 | 17 | A. no candidate passed Channel 1 (gate had nothing to test) (15); C. shadow rejects a Channel-1-passing candidate (DISCARDED DETECTION) (2) |
| 15 | Channel 2 suite shipped | 9 | -- | -- |

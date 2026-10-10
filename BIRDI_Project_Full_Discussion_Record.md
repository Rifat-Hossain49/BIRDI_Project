# BIRDI Project: Full Discussion and Development Record

## 1. Purpose of This Document

This document records the complete technical journey discussed during the BIRDI project. It is a structured summary rather than a verbatim chat transcript. Repeated troubleshooting exchanges have been consolidated into their final decisions, implementations, results, and lessons.

No passwords, API tokens, Hugging Face tokens, or other credential values are included.

---

## 2. Original Research Direction

The project initially explored a JEPA-inspired code-generation pipeline. The intended idea was:

1. Read a programming problem and its reference solution.
2. Convert the solution into a semantic graph.
3. Encode the problem statement and target graph into latent representations.
4. Train a JEPA predictor to map the problem representation to the solution-graph representation.
5. Decode the predicted graph latent into a graph.
6. Compile the decoded graph into code without allowing a final code LLM to bypass the graph.

The key research objective was not simply to ask a large language model to generate code. The intended contribution was to learn a structured intermediate solution representation and make final code generation depend on that representation.

---

## 3. AST Versus Semantic Graphs

### Initial concern

An AST was initially considered as the graph representation. This was challenged because an AST primarily captures syntax and does not fully represent the algorithm's semantic state transitions or data dependencies.

### Revised decision

The project moved toward a combined semantic graph containing:

- state-transition information;
- control-flow relationships;
- data-flow relationships;
- variable reads and writes;
- branch and loop transitions;
- return relationships.

The graph extractor still uses Python's AST parser as a reliable front end, but the AST is not treated as the final representation. Instead, an algorithm transforms parsed syntax into a semantic state-transition-plus-data-flow graph.

Example node types included:

- `INPUT`
- `DATA`
- `INITIALIZE`
- `ASSIGN`
- `CONDITION`
- `LOOP`
- `RETURN`

Example edge types included:

- `next`
- `reads`
- `writes`
- `true_branch`
- `false_branch`
- `loop_body`
- `exit`
- `returns`

This design was intended to retain the reliability of parsing while representing more of the solution's meaning.

---

## 4. Initial Kaggle JEPA Notebook

The first major engineering task was building a Kaggle notebook that:

1. Loaded `Instruction`, `Input`, and reference `Output` code.
2. Extracted pseudo-label semantic graphs from reference solutions.
3. Encoded problem text and graph JSON with a frozen pretrained embedding model.
4. Trained a JEPA predictor from problem latent to graph latent.
5. Plotted loss and retrieval metrics.
6. Optionally trained a graph decoder.
7. Printed intermediate outputs so learning progress could be inspected.

### Directory problems

Several early Kaggle runs failed because uploaded package files appeared directly at a Kaggle dataset root rather than under the expected repository directory. Other issues included:

- Kaggle dataset names being normalized into different path names;
- notebooks assuming `/kaggle/input/birdi-jepa-project`;
- package files appearing under paths such as `/kaggle/input/.../birdi_jepa`;
- ZIP archives created on Windows containing backslashes in member names;
- the CSV dataset appearing under Kaggle's nested `/kaggle/input/datasets/...` layout.

### Directory solution

The setup logic was changed to:

- recursively inspect `/kaggle/input`;
- identify package roots by required files rather than fixed folder names;
- locate the CSV recursively by filename;
- copy the package into `/kaggle/working/birdi_jepa` when needed;
- insert the resolved project root into `sys.path`;
- print all discovered paths before training;
- create ZIP archives with forward-slash paths.

This made the notebook resilient to Kaggle's input-directory normalization.

---

## 5. Embedding and JEPA Training

### Frozen embedding model

A Qwen embedding model was used to encode:

- the problem statement;
- the semantic graph or typed IR target.

The embedding encoder remained frozen. The JEPA predictor was the principal learned mapping between problem latent and target solution-representation latent.

Using an encoder-only model for embeddings was considered appropriate because this stage requires representation learning rather than autoregressive generation. CodeT5 was discussed as an alternative, but replacing the embedding model with CodeT5 was not considered inherently better. CodeT5's main advantage was in structured sequence generation, while a dedicated embedding model was better suited to retrieval and latent alignment.

### JEPA objective

The JEPA predictor learned:

```text
problem embedding -> predicted solution-graph/IR embedding
```

The target graph/IR embedding was produced by a frozen target encoder. The predictor was trained to align its output with the target representation.

### Contrastive learning

Contrastive learning was added to prevent the predictor from merely producing vectors close to an average target. In-batch targets acted as negatives:

- the correct problem-target pair was the positive;
- other graph targets in the batch were negatives;
- similarity-based cross-entropy encouraged correct retrieval.

### Representational-collapse concern

Collapse was a genuine risk because a simple cosine or regression objective can allow many problems to map toward similar vectors.

The discussed and implemented defenses included:

- in-batch contrastive loss;
- target variance regularization;
- covariance or decorrelation regularization;
- monitoring per-dimension standard deviation;
- monitoring pairwise cosine similarity;
- retrieval@K metrics;
- comparing predicted latent similarity across unrelated prompts;
- keeping the target encoder frozen;
- using sufficiently diverse batches.

The notebook was updated to make anti-collapse diagnostics visible rather than relying on training loss alone.

---

## 6. Early JEPA Results

One full Python-dataset run used 11,977 rows and produced encouraging latent-alignment results:

- final cosine similarity: approximately `0.8728`;
- retrieval@1: approximately `0.6007`;
- retrieval@5: approximately `0.8613`;
- retrieval@10: approximately `0.9348`.

These results suggested that the JEPA predictor and retrieval space had learned useful problem-to-solution relationships.

However, high latent retrieval quality did not automatically yield correct decoded graphs or correct final code.

---

## 7. Decoder Failure and Diagnosis

### Observed failure

For a GCD problem, the generated graph contained incorrect semantics such as:

```python
while gcd <= y:
    if gcd % 2 == 0:
        gcd = gcd * gcd
```

The deterministic graph-to-code compiler faithfully emitted incorrect code from this graph.

### Important conclusion

The final compiler was not the primary bottleneck. The decoded graph itself was wrong.

This established a useful diagnostic boundary:

```text
correct retrieved/predicted latent + wrong decoded graph
    -> decoder bottleneck

wrong retrieved graph neighborhood
    -> JEPA/retrieval bottleneck

correct graph + wrong code
    -> deterministic compiler bottleneck
```

### Added diagnostics

The notebook was changed to print:

- the predicted graph-latent similarity between test problems;
- top-K retrieved graph prototypes;
- decoded graph JSON;
- code compiled from the top retrieved graph;
- code compiled from the generated graph.

This separated retrieval quality from generative-decoder quality.

### Rare-family sampling

Focused sampling was added for algorithm families such as:

- GCD and LCM;
- Fibonacci;
- factorial;
- common list-processing operations.

This prevented random dataset subsampling from excluding rare but important algorithm families.

### Recursive compilation

The deterministic compiler was improved to support self-recursive graph labels, allowing correct recursive GCD graphs to compile into code such as:

```python
def solution_gcd(a, b):
    if b == 0:
        return a
    return solution_gcd(b, a % b)
```

---

## 8. CodeT5 and Decoder Strategy

### Model choice discussion

The decoder was intended to generate or repair graph JSON, not final solution code.

CodeT5+ 770M was selected because encoder-decoder models naturally fit conditional structured generation:

```text
problem + predicted latent + retrieved structures -> target graph/IR
```

An encoder-decoder model can attend to the complete source context before producing the target. A decoder-only causal LLM must represent both conditioning input and output in one autoregressive stream and is generally less constrained for exact transformation tasks.

### Why not a much larger model on Kaggle

The main limitation was not only model quality but runtime and memory:

- full-dataset decoder training exceeded Kaggle's practical session limits;
- 1024-token source and target lengths were expensive;
- two T4 GPUs did not automatically accelerate ordinary single-process fine-tuning;
- 770M full fine-tuning was already costly.

The practical middle path was:

- CodeT5+ 770M;
- approximately 2,048 focused decoder rows;
- one epoch for a 3-4 hour test;
- 512-token source and target limits;
- batch size 1;
- gradient accumulation;
- gradient checkpointing;
- Adafactor or another memory-conscious optimizer.

### Decoder training interpretation

The decoder was trained to transform context into the correct graph representation. It was not trained to output Python code directly.

The intended input was:

```text
problem statement
+ predicted JEPA graph/IR latent
+ top-K retrieved pseudo graphs/IR examples
```

The target was the pseudo-label graph/IR extracted from the reference solution.

### Why unseen problems still failed

Several methodological causes were identified:

- the target graph JSON was too verbose and weakly constrained;
- decoder training data was small relative to the transformation complexity;
- pseudo graphs inherited extractor noise;
- retrieval examples could be superficially similar but algorithmically wrong;
- a 770M model had limited compositional repair capacity;
- one epoch mainly learned formatting and frequent patterns;
- latent vectors were difficult to inject into a text model effectively;
- no execution-aware decoder objective guaranteed semantic correctness.

---

## 9. Retrieval-Augmented Decoding

Retrieval augmentation was judged useful, but not as a replacement for learning.

### Retriever database construction

The training set contained problem-solution pairs but no manually prepared graph database. This was resolved by automatically constructing the retrieval database:

1. Parse every training solution.
2. Extract its pseudo semantic graph or typed IR.
3. Serialize and store that representation.
4. Embed it with the target encoder.
5. Store the problem text, source code, structure, and embedding.

Therefore, no hand-labeled graph dataset was required.

### What the decoder receives

The intended decoder context became:

```text
problem statement
+ predicted JEPA target embedding
+ top-K retrieved pseudo structures
```

The retrieved structures provide concrete algorithmic prototypes. The predicted latent provides a soft global solution target. The problem statement provides exact task requirements.

### LLM-generated retrieval context

Using an LLM to generate a graph instead of retrieval was discussed. The conclusion was:

- an LLM-generated candidate can be useful as an additional proposal;
- it should not be called retrieval because it is not grounded in stored examples;
- it can hallucinate structures and silently bypass the JEPA contribution;
- a hybrid candidate pool is safer than replacing evidence-grounded retrieval.

### Fallback debate

A fallback from invalid decoded graph to the top retrieved graph was proposed as a production safeguard. It was rejected for research evaluation because it could artificially polish poor decoder performance and obscure whether the learned pipeline worked.

The agreed principle was:

- report decoder failures honestly;
- improve the method rather than hide failures;
- use fallback only as a separately reported deployment baseline.

---

## 10. Transition from Loose Graph JSON to Typed IR/DSL

Loose graph JSON was eventually judged too permissive. It allowed locally plausible but globally meaningless node labels and transitions.

The project moved toward a typed algorithmic intermediate representation, or IR/DSL.

### Meaning of typed IR/DSL

Instead of predicting arbitrary text labels, the decoder predicts operations from a restricted grammar, for example:

```text
Function(name, params, body)
Assign(target, expression)
If(condition, then_body, else_body)
While(condition, body)
For(variable, iterable, body)
Return(expression)
Call(function, arguments)
BinaryOp(operator, left, right)
Compare(operator, left, right)
```

The IR can still be represented as a graph or tree. The difference is that its node and edge semantics are typed and grammar-constrained.

### Benefits

- fewer invalid structures;
- easier deterministic compilation;
- clearer semantic validation;
- easier constrained decoding;
- easier composition of known algorithmic modules;
- less output-token overhead than verbose graph JSON;
- better suitability for eventual RTL lowering.

The revised notebook became a retrieval-augmented typed-IR JEPA experiment.

---

## 11. Desired Generalization Behavior

The project goal was not simple training-example memorization. The desired behavior was compositional generalization, including examples such as:

- training on averaging positive values, then handling averaging negative values;
- training on two-input GCD, then handling four-input GCD;
- composing GCD and LCM into a task that sums both results;
- modifying known algorithms through changed conditions or data types.

The discussion concluded that small decoder fine-tuning alone was unlikely to provide this ability. A stronger pretrained model should contribute broad algorithmic knowledge, while JEPA, retrieval, and typed IR should guide and constrain its solution.

---

## 12. Transition to RTL Generation

The long-term target became RTL generation rather than Python code generation.

This introduced several new challenges:

- RTL datasets are much smaller than general code datasets;
- syntax correctness is insufficient;
- cycle-accurate temporal behavior matters;
- reset behavior, signedness, bit widths, overflow, and handshake timing matter;
- different RTL implementations can be functionally equivalent;
- verification quality becomes as important as generation quality.

### Handling RTL-data scarcity

Suggested approaches included:

- modular retrieval rather than exact whole-design retrieval;
- automatically extracting reusable RTL motifs;
- synthetic specification generation;
- mutation-based training examples;
- simulation-generated counterexamples;
- parameterized templates;
- self-training with verified candidates;
- retrieval at module, protocol, arithmetic, or FSM level;
- using pretrained code models for prior knowledge while grounding output through tools.

---

## 13. RTL Model Evaluation Work

Separate notebooks were developed to evaluate open RTL/code models without fine-tuning.

Benchmarks discussed included:

- VerilogEval v2;
- RTLLM v2;
- ChipBench-SC;
- CVDP cid03.

Models discussed included:

- Qwen3.5-9B;
- Qwen2.5-Coder-7B-Instruct;
- Qwen2.5-Coder-14B-Instruct;
- Qwen2.5-Coder-32B-Instruct;
- DeepSeek-Coder-6.7B-Instruct;
- DeepSeek-Coder-33B-Instruct;
- DeepSeek-Coder-V2-Lite;
- StarCoder2-7B/15B;
- QwQ-32B.

### Kaggle constraints

Large benchmark/model sweeps hit several practical limits:

- 12-hour execution timeout;
- limited writable output disk;
- repeated model downloads;
- 14B and 32B model memory requirements;
- running several models sequentially;
- benchmark repositories with inconsistent formats.

The lesson was to load one quantized model at a time, keep generated artifacts small, remove models between runs, and avoid saving model caches as notebook output.

---

## 14. ChipMATE Paper Discussion

The paper `2605.12857v1.pdf` became a central reference.

### ChipMATE concept

ChipMATE uses two cooperating agents:

- a Verilog-generation agent;
- a Python-reference-model agent.

At each turn, each agent samples `K` candidates. The system forms a `K x K` pairing matrix, evaluates Verilog/Python pairs, selects the best-performing pair as the shared prefix for the next turn, and repeats.

Each agent has its own policy. During GRPO training:

- candidates sharing one prefix form a reward group;
- rule-based execution reward evaluates candidates;
- group-relative normalized advantages are computed;
- each policy receives its own gradients;
- the two policies collaborate during rollout but are optimized separately.

### SFT, RL, and multi-agent RL

The discussed training sequence was:

1. Supervised fine-tuning teaches output formats and basic task behavior.
2. Reinforcement learning rewards executable and correct outputs.
3. Multi-agent RL trains Verilog and Python policies using their interaction and cross-verification outcomes.

### Strengths identified

- no golden testbench is needed during inference;
- executable Python models provide a behavioral oracle candidate;
- Verilog and Python candidates cross-check one another;
- the KxK pairing creates richer evaluation than one-to-one pairing;
- execution-based reward is more reliable than textual self-critique;
- released model checkpoints and reproduction code make follow-up work possible.

### Weaknesses and open questions identified

- Verilog and Python agents can agree on the same wrong interpretation;
- random testing may miss rare temporal and arithmetic corner cases;
- oracle correctness is not guaranteed;
- generated Python models may omit cycle-level behavior;
- limited test coverage can produce false confidence;
- finite simulation does not prove correctness;
- repair can overfit observed counterexamples;
- results may depend strongly on model family, prompt, and sampling budget;
- computational cost grows with KxK candidate evaluation;
- benchmark evaluation and unsupported testbench formats can distort reported results.

### Same-family versus different-family hypothesis

It was hypothesized that using the same Qwen family for both RTL and Python agents could increase correlated errors. An experiment compared same-family and different-family oracle generation.

The result was contrary to the hypothesis: the same-family configuration did not perform worse and appeared stronger in the tested setting. Therefore, model-family diversity cannot currently be claimed as an improvement. The result suggested that role specialization, model competence, prompt compatibility, and executable verification may matter more than family diversity alone.

---

## 15. Verification Pipeline Design

An expanded multi-agent verification pipeline was designed:

```text
User RTL specification
  |
  v
Spec and interface extraction
  |
  v
RTL generation
  |
  +--> independent Python/reference generation
  |
  +--> directed/random test generation
  |
  +--> properties and assertions
  |
  v
Static compilation and interface checks
  |
  v
RTL-versus-reference simulation
  |
  v
Metamorphic and coverage checks
  |
  v
Bounded formal checks when applicable
  |
  v
Responsibility diagnosis and repair
  |
  v
Final blind benchmark evaluation
```

### Why use a Python reference and a testbench

They serve different roles:

- the Python model computes expected behavior;
- the SystemVerilog testbench drives the DUT, captures outputs, and communicates with simulation;
- Icarus Verilog or Verilator executes the RTL/testbench combination;
- the harness compares RTL outputs with expected outputs from the reference.

A testbench alone still requires expected values or properties. A Python oracle makes large-scale constrained-random comparison easier.

### Compilation check

Compilation verifies that RTL is syntactically legal, elaborates, and matches the expected module interface. It does not establish functional correctness.

The discussed order was:

1. Compile the candidate.
2. If compilation fails, repair syntax/interface problems.
3. If compilation succeeds, simulate against the oracle.
4. If behavior mismatches, repair semantic behavior.

At one point, repair was restricted to cases that both failed compilation and mismatched the oracle. This was recognized as a specific experimental choice rather than a generally correct rule, because compile failure prevents meaningful behavioral simulation and functionally wrong but compilable RTL also needs repair.

### Metamorphic testing

Metamorphic checks were proposed to reduce dependence on a potentially incorrect oracle. Examples include:

- commutative input swapping for commutative arithmetic;
- reset invariants;
- monotonic counter relationships;
- scaling or translation relationships when mathematically valid;
- protocol invariants under inserted stalls;
- repeated input sequences producing repeatable state behavior.

These properties test relationships between executions rather than only comparing against one exact expected trace.

### Coverage-directed testing

The suggested progression was:

1. Start with random tests.
2. Add directed corner cases.
3. Collect line/toggle/branch/FSM coverage with Verilator where possible.
4. Identify uncovered states and transitions.
5. Generate new tests targeting uncovered behavior.
6. Add discovered failures to a permanent regression bank.

### Bounded checking

Bounded formal checking was considered especially valuable for reducing false agreement. For small designs, Yosys and `yosys-smtbmc` can check properties over all input sequences up to a fixed depth. This is stronger than testing 1,000 random vectors, although it is still bounded and property-dependent.

### Mutation testing

Mutation testing was proposed to evaluate the verifier itself:

- flip operators;
- alter constants;
- remove reset assignments;
- change comparison directions;
- shift state transitions;
- perturb widths or signedness.

Useful tests and properties should reject these mutants. A verifier that accepts most mutants is not providing strong evidence.

---

## 16. Earlier Multi-Agent VerilogEval Implementation

An experimental notebook compared:

- a single RTL-generation agent;
- a multi-agent pipeline with RTL, Python oracle, repair, and critic roles.

One agreed small-model setup was:

```text
Single-agent baseline:
  Qwen2.5-Coder-7B-Instruct

Multi-agent RTL generator:
  Qwen2.5-Coder-7B-Instruct

Python oracle:
  deepseek-coder-6.7b-instruct

Repair model:
  Qwen2.5-Coder-7B-Instruct

Independent critic:
  StarCoder2-7B
```

The purpose of using a different critic family was to reduce self-confirmation bias. However, later experiments showed that diversity alone did not guarantee improvement.

### Pass@1 clarification

Pass@1 must be calculated only from each method's final frozen candidate, not intermediate candidates that failed and were repaired.

For `N` benchmark tasks:

```text
pass@1 = number of final candidates passing the official testbench / N
```

The official VerilogEval flow compiles:

- generated `TopModule`;
- benchmark `RefModule` when required;
- official testbench;

and executes the resulting simulation with Icarus Verilog.

### Experimental lesson

Initial multi-agent runs did not clearly outperform the single-agent baseline. Increasing task number and complexity was reasonable, but the deeper conclusion was that more agents do not automatically improve results. Oracle quality, repair prompts, acceptance policy, and unbiased evaluation are decisive.

---

## 17. TRIAGE-RTL: Final Implemented Inference Approach

The final implemented system was called TRIAGE-RTL. It is a training-free reliability layer on top of the released ChipMATE Verilog and Python agents.

### Implemented contributions

1. **Full Verilog x Python matrix**
   - Every Verilog candidate is scored against every Python candidate.
   - This replaces index-only pairing.

2. **Shared stimulus bank**
   - Multiple fixed random seeds.
   - Directed cases.
   - Fresh random cases in repair rounds.
   - Permanent regression cases from prior mismatches.

3. **Spec-only consensus witnesses**
   - Both agents independently propose tests from the specification.
   - Only conservative agreed witnesses are retained.

4. **Responsibility routing**
   - Evidence determines whether the likely weak component is Verilog, Python, or both.

5. **Counterexample minimization**
   - Failing input sequences are reduced before repair.

6. **Yosys/static localization**
   - Structural analysis identifies suspicious RTL regions and signals.

7. **Evidence-gated repair**
   - New candidates must improve current evidence.

8. **Backtracking and non-regression**
   - Previously stronger candidates are restored when repairs regress.

9. **Hard compute controls**
   - Maximum repair rounds.
   - Maximum LLM completions.
   - Session time guard.
   - Circuit breaker for repeated infrastructure failures.

10. **Blind official evaluation**
    - Official RTLLM testbenches are used only after the final RTL candidate is frozen.

11. **Atomic checkpointing**
    - State is saved after repair rounds and completed tasks.

### What is not yet fully implemented

Several proposed ideas should not be claimed as current TRIAGE-RTL functionality:

- complete coverage-guided test generation;
- full metamorphic-property library;
- general SystemVerilog assertion synthesis and validation;
- mutation-score-based verifier acceptance;
- broad bounded formal verification with `yosys-smtbmc`;
- a fully independent learned critic in the final TRIAGE-RTL run;
- complete support for every RTLLM official evaluator format.

These remain the next extension directions.

---

## 18. Final TRIAGE-RTL Kaggle Configuration

### Hardware

- Kaggle GPU environment;
- two Tesla T4 GPUs;
- one model server per GPU.

### Models

- Verilog agent: `core12345/ChipMATE-V-4B`;
- Python agent: `core12345/ChipMATE-P-4B`;
- both based on Qwen3.5-4B;
- exact model revisions were pinned;
- each checkpoint was approximately 8.46 GiB.

### Runtime services

Each checkpoint was served through a separate local vLLM OpenAI-compatible endpoint:

```text
GPU 0 -> Verilog agent -> port 8001
GPU 1 -> Python agent  -> port 8002
```

Important server settings included:

- FP16 weights;
- 8,192-token model context;
- maximum four sequences per server;
- 90% GPU-memory utilization.

### Experiment budget

- 18 maximum completions per problem;
- three initial Verilog candidates;
- three initial Python candidates;
- maximum three repair rounds;
- multiple random seeds and directed vectors;
- blind official evaluation after candidate freeze.

### Reproducibility

The run pinned:

- ChipMATE repository commit;
- RTLLM repository commit;
- Hugging Face model revisions;
- vLLM version;
- completion budget;
- random seeds.

The reusable notebook was kept token-free. A private transient execution copy was used for gated model download, and credential values were never included in the reusable artifact or this document.

---

## 19. Final TRIAGE-RTL Run Results

### Runtime

- total runtime: `12,917.9` seconds;
- approximately 3 hours 35 minutes;
- accelerator: two Tesla T4 GPUs;
- all 50 discovered RTLLM tasks produced final candidates.

### Aggregate results

```text
Tasks completed:                         50
Tasks supported by current evaluator:   20
Tasks evaluator could not handle:       30
Compiled among evaluable tasks:         19/20 = 95%
Functional passes among evaluable:      18/20 = 90%
Functional passes over all 50:          18/50 = 36%
Average LLM completions per task:        16.12
Average repair rounds per task:          2.62
```

### Two observed evaluable failures

1. `Arithmetic/Other/fixed_point_substractor`
   - final candidate failed compilation.

2. `Memory/LIFO/LIFObuffer`
   - final candidate compiled;
   - official functional simulation failed.

### Successful examples among evaluable tasks

Successful final evaluations included examples such as:

- BCD adder;
- 3-bit and 4-bit comparators;
- 8-bit multiplier;
- fixed-point adder;
- floating-point multiplier;
- 64-bit subtractor;
- up/down counter;
- sequence detector;
- LFSR;
- barrel shifter;
- several frequency dividers;
- ROM;
- RISC-V instruction register;
- square-wave generator.

### Critical evaluation limitation

Thirty tasks were labeled `evaluator_unsupported`. This does not mean the model failed those tasks. It means the current official-evaluation wrapper could not process their testbench or repository format.

Therefore:

- `18/20 = 90%` is a score on a supported subset and is selection-biased;
- `18/50 = 36%` incorrectly treats evaluator limitations as model failures;
- neither number is yet a valid full RTLLM pass@1 score.

The current result demonstrates end-to-end pipeline execution, not a complete benchmark claim.

---

## 20. Contribution of the Current Approach

The main contribution is not a newly trained RTL foundation model. It is a training-free reliability and repair layer over released ChipMATE agents.

### Methodological contribution

- expands candidate evaluation from paired outputs to a full cross-product;
- introduces diverse shared stimuli and a growing regression bank;
- adds independently generated spec-only witnesses;
- routes repair responsibility using evidence;
- minimizes counterexamples before asking for repair;
- localizes RTL issues with deterministic tools;
- applies non-regression, best-state retention, and backtracking;
- preserves blind official evaluation;
- makes runtime and completion budgets explicit.

### Engineering contribution

- robust Kaggle setup for gated models;
- one vLLM service per GPU;
- pinned model and repository revisions;
- recoverable checkpoints;
- circuit breaker and time guard;
- reproducible output summaries.

### Claim boundary

The current experiment does not yet establish that TRIAGE-RTL outperforms vanilla ChipMATE. It shows that the method runs end-to-end and achieves strong results on the 20 tasks supported by the evaluator.

An improvement claim requires a matched baseline and complete evaluation coverage.

---

## 21. Correct Pass@1 Comparison Against ChipMATE

A valid comparison should use:

1. the same complete RTLLM task set;
2. the same ChipMATE-4B model checkpoints;
3. the same prompts and sampling parameters where applicable;
4. the same maximum 18 completions per task;
5. the same official evaluator;
6. one frozen final RTL candidate per task;
7. no use of official testbenches during repair;
8. multiple random seeds;
9. mean pass@1 and confidence intervals;
10. paired per-task outcome analysis.

For 50 fully evaluable tasks:

```text
pass@1 = number of final RTL candidates passing official tests / 50
```

The most defensible study is:

```text
Baseline A: single ChipMATE Verilog agent
Baseline B: vanilla released ChipMATE V/P inference
Method:     TRIAGE-RTL with the same completion budget
```

Useful paired analysis should report:

- tasks both methods pass;
- tasks only vanilla ChipMATE passes;
- tasks only TRIAGE-RTL passes;
- tasks both fail;
- repair recovery count;
- repair regression count;
- compile-to-functional failure breakdown;
- time and completions per solved task.

---

## 22. Recommended Next Work

### Priority 1: Complete the evaluator

Support all 50 RTLLM testbench formats. The 30 unsupported tasks are currently the largest obstacle to a publishable comparison.

### Priority 2: Reproduce vanilla ChipMATE

Run the released ChipMATE inference under the same:

- 4B checkpoints;
- task set;
- completion budget;
- hardware;
- random seeds;
- official evaluator.

### Priority 3: Run ablations

Suggested ablations:

```text
A0: vanilla ChipMATE
A1: + full V x P matrix
A2: + directed/shared regression bank
A3: + consensus witnesses
A4: + responsibility routing
A5: + counterexample minimization/localization
A6: + non-regression and backtracking
```

This will reveal which components create measurable improvement.

### Priority 4: Strengthen verification

Add:

- metamorphic properties;
- coverage-guided stimulus generation;
- mutation testing of the oracle package;
- bounded formal checking for suitable modules;
- assertion vacuity checks;
- independent oracle validation.

### Priority 5: Analyze the two known failures

For `fixed_point_substractor`:

- inspect final compiler errors;
- determine whether the selected candidate ever compiled internally;
- tighten compile-aware acceptance.

For `LIFObuffer`:

- inspect official mismatch traces;
- compare internal regression coverage with the failing official sequence;
- add LIFO overflow, underflow, simultaneous push/pop, reset, and pointer-wrap tests.

### Priority 6: Measure efficiency

The average of 16.12 completions and 2.62 repair rounds indicates that many tasks consume most of the allowed budget. Measure:

- pass gain per repair round;
- pass gain per additional completion;
- time per recovered task;
- early-stop quality;
- whether some evidence checks can be cached or batched.

---

## 23. Main Lessons from the Journey

1. A syntactic AST is a useful parser output but not a sufficient semantic target.
2. Strong latent retrieval does not guarantee a strong generative decoder.
3. Deterministic graph-to-code compilation exposes upstream semantic failures honestly.
4. Loose graph JSON is difficult to decode reliably; typed IR is a better target.
5. Retrieval should ground generation, but it must not hide decoder failures.
6. Larger models help only when the representation, objective, and verifier are sound.
7. Multiple agents do not automatically outperform one strong agent.
8. Model-family diversity is a hypothesis, not an established benefit.
9. Compilation, simulation, reference comparison, metamorphic checks, and formal checks provide different evidence and should not be conflated.
10. An incorrect oracle can make two agents confidently agree on a wrong design.
11. Official benchmark tests must remain blind during repair.
12. Unsupported evaluator cases cannot be counted as model failures or silently excluded.
13. Equal model and completion budgets are necessary for a fair baseline comparison.
14. Checkpointing, path resilience, and disk/runtime controls are essential for cloud experiments.
15. The next major gain is likely to come from verifier quality and complete evaluation, not simply adding another agent.

---

## 24. Important Project Artifacts

The discussion referred to or produced the following major artifacts:

- `notebooks/birdi_jepa_kaggle.ipynb`
  - JEPA, retrieval, graph/typed-IR training and inference notebook.

- `birdi_jepa/embedding.py`
  - frozen text/structure embedding utilities.

- `birdi_jepa/training.py`
  - JEPA, contrastive, and anti-collapse training logic.

- `birdi_jepa/decoder.py`
  - graph/IR decoder training and generation.

- `birdi_jepa/state_graph.py`
  - semantic graph extraction.

- `birdi_jepa/algorithm_ir.py`
  - typed algorithmic IR representation.

- `birdi_jepa/codegen.py`
  - deterministic structure-to-code compilation.

- `TRIAGE_RTL_RTLLM_Kaggle.ipynb`
  - final reusable TRIAGE-RTL Kaggle notebook.

- `TRIAGE_RTL_Kaggle_Bundle.zip`
  - notebook, reviewed pipeline source, and instructions.

- `outputs/triage-rtl-kaggle-review/triage_rtl_kaggle.py`
  - reviewed TRIAGE-RTL implementation.

- `2605.12857v1.pdf`
  - ChipMATE paper used for analysis.

- `Current_Implementation.jpg`
  - diagram of the earlier/current implementation during the project journey.

- `Graph_Encoder Based Pipeline.jpg`
  - diagram of the earlier graph-encoder-based design.

---

## 25. Final Position

The project evolved through three major stages:

```text
Stage 1:
Problem -> JEPA latent -> semantic graph -> deterministic Python code

Stage 2:
Problem -> JEPA latent -> retrieval-augmented typed IR -> deterministic code

Stage 3:
RTL specification -> ChipMATE V/P candidates -> evidence-based triage,
repair, and backtracking -> blind official RTL evaluation
```

The most mature current artifact is TRIAGE-RTL. Its strongest current contribution is a reproducible, evidence-guided, training-free multi-agent inference framework. The latest run is promising, but the next scientifically necessary step is not another model change. It is completing the evaluator and performing a matched, equal-budget pass@1 comparison with vanilla ChipMATE and targeted ablations.

# Introduction
**Incident Response End-to-End (IRENE)** is multi-step agentic benchmark for evaluating LLMs across the incident response lifecycle. The goal of this project is to address the gap of LLM benchmarks in the realm of cybersecurity by creating a benchmark that evaluates an LLMs ability to walk through the complete incident response lifecycle.

## The core idea
Most existing benchmarks treat security as a set of question-answer problems. For example, you give a model a question, it responds, and you score it. However, this does not reflect _real_ incident response (IR). 
IR is a branching decision tree where every action you take changes what information is available to you, and wrongs turns cost real time. You can compare it to those dating-sim games where your choices impact the ending of the game. Similar idea, anyways.

IRENE models an incident as a _directed graph of states_. The model gets scored not just on whether it reached the right answer but on the _quality_ of its reasoning path, how many false leads it followed, how many unnecessary actions it took, and whether its final report accurately reflects what happened. 

## Our contribution
The key technical contribution is state-dependent information disclosure. The model can only see what a real analyst would see at each step. Remember, think back to that dating-sim example - you can't see ahead of the current choice you're on, only the previous choices you've made and the choice you're presented with at that moment in time.

## Quickstart
```bash
python -m pip install -e ".[dev]"

irene list                                         # available incidents
irene run incidents/phishing_credential_theft.yaml --optimal   # offline, no API key

# Run a model — Claude:
python -m pip install -e ".[anthropic]"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
irene run incidents/phishing_credential_theft.yaml --judge

# ...or any OpenAI-compatible endpoint (vLLM, Together, Groq, Ollama, OpenAI):
python -m pip install -e ".[openai]"
irene run incidents/phishing_credential_theft.yaml \
  --provider openai --model <model-id> --base-url http://localhost:8000/v1
```

The analyst acts in **free text**; a resolver maps it onto the incident graph, so
scoring stays deterministic while the interface stays realistic.

## Documentation
- **[METHODOLOGY.md](METHODOLOGY.md)** — how IRENE scores a model and how that
  follows current agentic-benchmark literature (verifiable rule-based scoring +
  LLM-as-judge rubrics over the execution trace).
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to author a new incident and run
  the benchmark.


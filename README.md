# CharacterForge — Cartman fan voice demo

An unofficial local Windows demo combining a Cartman-style text persona, English microphone input, reference-conditioned speech, automatic emotion selection, a 2D animated character, captions, chat history and explicit memory. **Built with Llama** for the author's 3B LoRA backend; an optional local Qwen3 8B backend is also available. We did not train a new Cartman model.

![Project-redrawn Cartman fan illustration](private_assets/characters/avatar.svg)

**Character and voice material is intended for noncommercial fan research. South Park / Eric Cartman and original recordings and performances belong to their respective rights holders. No official affiliation, endorsement, or authorization to redistribute these character/reference assets or perform voice cloning is claimed.** Read [ASSET-RIGHTS.md](ASSET-RIGHTS.md). The framework's MIT license does not license those assets. This is not an assurance that publication or any particular use is lawful.

[中文安装和使用说明](README.zh-CN.md) · [Third-party terms](THIRD-PARTY-NOTICES.md) · [Release validation](VALIDATION.md)

## Included

- Current character interface, audio-driven mouth shapes, angry squeezed eyes, expression reset after speaking, subtitles and settings.
- English microphone ASR, pause detection, interruption, complete-utterance playback and continuous PCM playback.
- The existing Qwen3-TTS voice-clone provider and normal/sarcastic/angry reference profiles; automatic voice delivery selection.
- The original locally written 3B inference integration, original persona rules, memory and chat storage; optional Qwen3 8B.
- Necessary reference excerpts and project-redrawn SVG, with separate rights notices and source records. No claim of new voice-model training.

This release includes the application source and its character/reference assets. **Large model weights, Python environments and vendor runtimes are downloaded separately during explicit setup.** It is not a preinstalled single-file EXE or an embedded-device build.

## Windows setup

Baseline used in development: Windows 11, NVIDIA RTX 4060 Laptop 8 GB, 24 GB RAM, Python 3.12.15. These are a tested configuration, not a measured minimum. Reserve ample disk space (about 35 GB recommended for models, two CUDA environments, downloads and cache); place the project on a drive such as `D:\Projects\CharacterForge-Demo`. GPU requirements remain substantial despite the small source archive.

Use Windows x64 Python 3.12. Existing Python/driver installations are not replaced. From this folder run:

```bat
py -3.12 setup_demo.py install
py -3.12 setup_demo.py models
py -3.12 run.py check
py -3.12 run.py start --wait
```

The default 3B backend does not require Ollama. To enable the **optional 8B choice**, also run:

```bat
py -3.12 setup_demo.py ollama
py -3.12 setup_demo.py 8b
```

Or run `py -3.12 setup_demo.py all` for both backends. Initial downloads can exceed 10 GB; CUDA environments require additional space. Model access, upstream availability and their terms are separate from this repository. No paid API or token purchase is required by the app. Setup was not freshly exercised with every dependency/model download on a second clean PC; see VALIDATION.md.

After setup, double-click **Start Demo.cmd** and open http://127.0.0.1:7862/ . Use **Stop Demo.cmd** to close this instance. Start never installs or downloads. The application refuses to take over a different build on its ports. Close an older instance first. The microphone starts only when you enable it; use English for recognition. All inference stays on the local machine after setup.

## Known limits

This is a release candidate. Anger acting, voice similarity, repeated response patterns and end-to-end latency remain imperfect. The complete real-time target, minimum GPU requirements, embedded deployment, a clean second-PC install and long-duration stability have not been established. An optional 8B tag is downloaded through Ollama and can change upstream; Hugging Face snapshots and the Ollama runtime archive are fixed by revision/checksum. No performance guarantee is inferred from the size of this repository.

License separation: project-authored code MIT; third-party software/model terms independent; character/voice material has the unresolved rights status described in ASSET-RIGHTS.md. Adding noncommercial wording does not create rights over third-party material.

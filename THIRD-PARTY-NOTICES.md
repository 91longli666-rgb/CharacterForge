# Third-party software and model notices

The project-authored framework is MIT. Third-party code, model weights, characters, artwork, recordings and performances retain their own terms. See ASSET-RIGHTS.md for the separate and unresolved character/voice rights status.

| Dependency | License / upstream |
|---|---|
| Cartman text LoRA | [Chun0927/eric_cartman_llama3.2_3b](https://huggingface.co/Chun0927/eric_cartman_llama3.2_3b), metadata declares llama3.2; character/training rights are not established by that metadata |
| Quantized Llama-3.2 3B base | [unsloth/Llama-3.2-3B-Instruct-bnb-4bit](https://huggingface.co/unsloth/Llama-3.2-3B-Instruct-bnb-4bit); [Llama 3.2 terms](https://www.llama.com/llama3_2/license/) and applicable acceptable-use terms; **Built with Llama** when this backend is used |
| Qwen3-TTS 0.6B Base | [Qwen/Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), Apache-2.0; qwen-tts 0.1.1 source notice in licenses/ |
| Qwen3 8B | [Qwen/Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), Apache-2.0, optional Ollama backend |
| Whisper-small / faster-whisper / CTranslate2 | MIT upstream; PyAV/FFmpeg and bundled libraries have independent notices |
| Ollama 0.40.4 | MIT principal code, independently downloaded official Windows package and bundled-library terms |
| PyTorch / Transformers / PEFT / bitsandbytes / CUDA and others | Independent upstream licenses. CUDA/NVIDIA terms are not replaced by framework MIT |

Fixed Hugging Face repositories and revisions are in config/model-sources.json. Torch/CUDA runtime package versions are locked separately for text and voice. Software license texts recorded during development are in licenses/. Model/license metadata is a provenance record, not an assurance that all character, training data or performer rights are cleared.

No third-party weights, Python environments, NVIDIA drivers or Ollama binaries are redistributed in this source repository. Setup fetches dependencies from their identified upstreams; it does not change system drivers, uninstall Python, or start paid APIs. The existence of an upstream download does not resolve otherwise missing character or voice permissions.

Project adaptations of the Qwen runtime, including CUDA graph wrappers, are supplied separately from the installed vendor files; vendor environments are not patched. Upstream Qwen software is Apache-2.0. Preserve its notices when redistributing it or adaptations covered by that license.

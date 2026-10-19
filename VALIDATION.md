# Validation of 1.0.0-cartman-demo-rc1

The release preserves the current local Cartman runtime rather than substituting the Milo/system-voice public example. No new Cartman model was trained. Packaging checks and source tests do not establish copyright permission.

## Previous local application validation

The development checkpoints include actual local model answers, reference-conditioned voice output, browser playback, microphone recognition, captions, emotion/mouth animation and interruption tests. The user accepted continuous playback without audible gaps or missing words. The previous final recovery test restored the original private application and generated a real 3B answer and cloned WAV. These are previous tests of the same runtime, not a new clean-machine installation of this release.

## Release assembly checks

The public snapshot uses an allowlist. Source-snapshot hashes identify runtime files copied byte for byte from the development version. The bundled original 3B engine additionally accepts an optional model location; inference logic is unchanged. WAV files receive RIFF copyright/comment metadata and adjacent provenance notices; all four PCM streams are checked byte for byte against the original references. The SVG receives a metadata notice without changing drawing elements. Runtime audio hash metadata is refreshed to match the tagged WAVs.

No developer Git history, credentials, conversation or memory databases, original source videos, personal microphone recordings, model weights, vendor binaries, Python environments or caches are included. New users download models and runtimes separately using explicit setup commands.

Final local checks: 28 unit tests passed (11 character/memory, 7 adaptive delivery, 3 presentation, 7 dialogue startup), plus five regression programs passed (speech mouth shapes, expression lifecycle/reset, continuous audio, PCM stream bridge, authenticated stream HTTP). Release verification checks every manifest file, Python syntax, 95 byte-identical source files, four WAV notices/checksums, SVG metadata and credential-token patterns. A temporary binding to the existing resources passed the new launcher's file check and was then removed. This did not install new environments, run fresh inference, restart services or validate a second computer.

## Not established

- A fresh second Windows PC installation, every large model/package download and new user permissions/device selection.
- Minimum VRAM/RAM, standalone EXE or embedded-device compatibility.
- Hours-long stability or the overall stop-speaking-to-audible-first-response target.
- A rights-holder authorization or a legal determination for the character, performance excerpts, voice cloning, or this release.

Anger quality, likeness, fixed response habits and latency remain known limitations. No stronger result is claimed by this packaging pass.

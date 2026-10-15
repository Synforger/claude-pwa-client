# Changes from upstream

This folder is a copy of [pipecat-client-ios-small-webrtc](https://github.com/pipecat-ai/pipecat-client-ios-small-webrtc)
1.3.0 (`ec380646b4f6e1cc50bcdf610c60103f49304bf5`), with `LICENSE` taken from the upstream default branch (the 1.3.0
tag has none). Every changed line carries a `cpc patch` comment, so `grep -rn "cpc patch" Sources` lists them all.

## Audio device per transport

`SmallWebRTCTransport(iceConfig:waitForIceGathering:audioDevice:)` takes an optional `RTCAudioDevice`. When it is set:

- `SmallWebRTCConnection` creates its peer connection from a factory built with that audio device (one factory per
  device, cached), so WebRTC plays and records through it instead of its own iOS audio device.
- The transport does not start its `AudioManager`, so the `playAndRecord` session configuration is not applied; the
  audio device configures `AVAudioSession` itself.

Without an audio device the transport behaves as upstream. The app passes a playback-only device for calls with the
microphone off, so iOS does not treat them as calls that use the microphone (`shell/ios/App/App/ListenOnlyAudioDevice.swift`).

## Warnings

Building the package as a local package shows its warnings. They are fixed without changing behavior:

- `shell/ios/App/Packages/pipecat-client-ios-small-webrtc/Sources/PipecatClientIOSSmallWebrtc/SmallWebRTCTransport.swift`: the ICE flush timer hops to the main actor explicitly; Optional values in the ICE
  payload are cast to `Any` explicitly; a failed disconnect after the connection fails is logged instead of dropped.
- `shell/ios/App/Packages/pipecat-client-ios-small-webrtc/Sources/PipecatClientIOSSmallWebrtc/types/SignallingMessage.swift`: inbound messages with a fixed `type` decode nothing (the synthesized decoder could
  not overwrite the constant).
- `shell/ios/App/Packages/pipecat-client-ios-small-webrtc/Sources/PipecatClientIOSSmallWebrtc/util/AudioManager.swift`: `.allowBluetooth` is spelled with its current name `.allowBluetoothHFP` (same value).

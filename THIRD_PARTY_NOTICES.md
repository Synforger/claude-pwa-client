# Third-Party Notices

claude-pwa-client は以下の OSS に依存している。 全 deps のライセンスは Apache License 2.0 (= 本リポジトリ自体のライセンス) と**互換**で、 GPL / AGPL / SSPL 等の strong copyleft はゼロ。 LGPL (= weak copyleft) は、 任意で入れる電話の会話の部品にだけ含まれる (= [下の説明](#weak-copyleft-説明))。

> 本 file は `scripts/gen-third-party-notices.py` で自動生成 (= `task gen-notices`)。 dependency を追加 / 削除 / version bump した時は再生成すること。

## License summary

| Ecosystem | License | Count |
|---|---|---|
| NPM | Apache-2.0 | 2 |
| NPM | BSD-3-Clause | 11 |
| NPM | CC0-1.0 | 1 |
| NPM | ISC | 3 |
| NPM | MIT | 124 |
| Python | Apache License 2.0 | 1 |
| Python | Apache-2.0 | 8 |
| Python | Apache-2.0 AND MIT | 1 |
| Python | Apache-2.0 OR BSD-2-Clause | 1 |
| Python | Apache-2.0 OR BSD-3-Clause | 1 |
| Python | Apache-2.0; MIT | 1 |
| Python | BSD-2-Clause | 1 |
| Python | BSD-3-Clause | 17 |
| Python | ISC | 1 |
| Python | MIT | 48 |
| Python | MIT OR Apache-2.0 | 1 |
| Python | MPL-2.0 | 4 |
| Python | PSF-2.0 | 2 |
| Python | UNKNOWN | 1 |

## Backend (Python) dependencies

| Package | License | URL |
|---|---|---|
| aiohappyeyeballs | PSF-2.0 | https://github.com/aio-libs/aiohappyeyeballs |
| aiohttp | Apache-2.0 AND MIT | https://github.com/aio-libs/aiohttp |
| aioice | BSD-3-Clause | https://github.com/aiortc/aioice |
| aiortc | BSD-3-Clause | https://github.com/aiortc/aiortc |
| aiosignal | Apache-2.0 | https://github.com/aio-libs/aiosignal |
| annotated-doc | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | MIT | https://github.com/annotated-types/annotated-types |
| anyio | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| attrs | MIT | https://www.attrs.org/en/stable/changelog.html |
| av | BSD-3-Clause | https://pyav.basswood-io.com |
| black | MIT | https://github.com/psf/black |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | MIT | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| claude-agent-sdk | MIT | https://github.com/anthropics/claude-agent-sdk-python |
| click | BSD-3-Clause | https://github.com/pallets/click/ |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| dnspython | ISC | https://www.dnspython.org |
| fastapi | MIT | https://github.com/fastapi/fastapi |
| flake8 | MIT | https://github.com/pycqa/flake8 |
| frozenlist | Apache-2.0 | https://github.com/aio-libs/frozenlist |
| google-crc32c | UNKNOWN | https://github.com/googleapis/python-crc32c |
| h11 | MIT | https://github.com/python-hyper/h11 |
| http_ece | MIT | https://github.com/martinthomson/encrypted-content-encoding |
| httpcore | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httpcore2 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| httptools | MIT | https://github.com/MagicStack/httptools |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| httpx-sse | MIT | https://github.com/florimondmanca/httpx-sse |
| httpx2 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| ifaddr | MIT | https://github.com/pydron/ifaddr |
| iniconfig | MIT | https://github.com/pytest-dev/iniconfig |
| jsonschema | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| markdown-it-py | MIT | https://github.com/executablebooks/markdown-it-py |
| mccabe | MIT | https://github.com/pycqa/mccabe |
| mcp | MIT | https://modelcontextprotocol.io |
| mdurl | MIT | https://github.com/executablebooks/mdurl |
| multidict | Apache License 2.0 | https://github.com/aio-libs/multidict |
| mypy_extensions | MIT | https://github.com/python/mypy_extensions |
| packaging | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pathspec | MPL-2.0 | https://python-path-specification.readthedocs.io/en/latest/index.html |
| platformdirs | MIT | https://github.com/tox-dev/platformdirs |
| pluggy | MIT |  |
| propcache | Apache-2.0 | https://github.com/aio-libs/propcache |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| py-vapid | MPL-2.0 | https://github.com/mozilla-services/vapid |
| pycodestyle | MIT | https://pycodestyle.pycqa.org/ |
| pycparser | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | MIT | https://github.com/pydantic/pydantic-core |
| pyee | MIT | https://github.com/jfhbrook/pyee |
| pyflakes | MIT | https://github.com/PyCQA/pyflakes |
| Pygments | BSD-2-Clause | https://pygments.org |
| PyJWT | MIT | https://github.com/jpadilla/pyjwt |
| pylibsrtp | BSD-3-Clause | https://github.com/aiortc/pylibsrtp |
| pyobjc-core | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-AVFoundation | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-Cocoa | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-CoreAudio | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-CoreMedia | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyobjc-framework-Quartz | MIT | https://github.com/ronaldoussoren/pyobjc |
| pyOpenSSL | Apache-2.0 | https://pyopenssl.org/ |
| pytest | MIT | https://docs.pytest.org/en/latest/ |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |
| pytokens | MIT | https://github.com/tusharsadhwani/pytokens |
| pywebpush | MPL-2.0 | https://github.com/web-push-libs/pywebpush |
| PyYAML | MIT | https://pyyaml.org/ |
| referencing | MIT | https://github.com/python-jsonschema/referencing |
| requests | Apache-2.0 | https://github.com/psf/requests |
| rpds-py | MIT | https://github.com/crate-py/rpds |
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice/ |
| sse-starlette | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| starlette | BSD-3-Clause | https://github.com/Kludex/starlette |
| structlog | MIT OR Apache-2.0 | https://github.com/hynek/structlog/blob/main/CHANGELOG.md |
| truststore | MIT | https://github.com/sethmlarson/truststore |
| typing-inspection | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | BSD-3-Clause | https://uvicorn.dev/ |
| uvloop | Apache-2.0; MIT |  |
| watchdog | Apache-2.0 | https://github.com/gorakhargosh/watchdog |
| watchfiles | MIT | https://github.com/samuelcolvin/watchfiles |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| yarl | Apache-2.0 | https://github.com/aio-libs/yarl |

## Frontend (npm production) dependencies

> devDependencies (= eslint / vitest / typescript / @vitejs/plugin-react 等) は 配布物 (= `dist/`) に含まれないため本 listing からは除外。

| Package | License | URL |
|---|---|---|
| @babel/runtime | MIT | https://github.com/babel/babel |
| @protobufjs/aspromise | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/base64 | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/codegen | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/eventemitter | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/fetch | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/float | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/path | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/pool | BSD-3-Clause | https://github.com/dcodeIO/protobuf.js |
| @protobufjs/utf8 | BSD-3-Clause | https://github.com/protobufjs/protobuf.js |
| @ricky0123/vad-web | ISC | https://github.com/ricky0123/vad |
| @types/debug | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/estree-jsx | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/estree | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/hast | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/mdast | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/ms | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/node | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/prismjs | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/unist | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/unist | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @ungap/structured-clone | ISC | https://github.com/ungap/structured-clone |
| @xterm/addon-canvas | MIT | https://github.com/xtermjs/xterm.js.git#master |
| @xterm/addon-fit | MIT | https://github.com/xtermjs/xterm.js.git#master |
| @xterm/addon-webgl | MIT | https://github.com/xtermjs/xterm.js.git#master |
| @xterm/xterm | MIT | https://github.com/xtermjs/xterm.js |
| bail | MIT | https://github.com/wooorm/bail |
| ccount | MIT | https://github.com/wooorm/ccount |
| character-entities-html4 | MIT | https://github.com/wooorm/character-entities-html4 |
| character-entities-legacy | MIT | https://github.com/wooorm/character-entities-legacy |
| character-entities | MIT | https://github.com/wooorm/character-entities |
| character-reference-invalid | MIT | https://github.com/wooorm/character-reference-invalid |
| comma-separated-tokens | MIT | https://github.com/wooorm/comma-separated-tokens |
| csstype | MIT | https://github.com/frenic/csstype |
| debug | MIT | https://github.com/debug-js/debug |
| decode-named-character-reference | MIT | https://github.com/wooorm/decode-named-character-reference |
| dequal | MIT | https://github.com/lukeed/dequal |
| devlop | MIT | https://github.com/wooorm/devlop |
| escape-string-regexp | MIT | https://github.com/sindresorhus/escape-string-regexp |
| estree-util-is-identifier-name | MIT | https://github.com/syntax-tree/estree-util-is-identifier-name |
| extend | MIT | https://github.com/justmoon/node-extend |
| fault | MIT | https://github.com/wooorm/fault |
| flatbuffers | Apache-2.0 | https://github.com/google/flatbuffers |
| format | MIT | https://github.com/samsonjs/format |
| guid-typescript | ISC | https://github.com/NicolasDeveloper/guid-typescript |
| hast-util-parse-selector | MIT | https://github.com/syntax-tree/hast-util-parse-selector |
| hast-util-to-jsx-runtime | MIT | https://github.com/syntax-tree/hast-util-to-jsx-runtime |
| hast-util-whitespace | MIT | https://github.com/syntax-tree/hast-util-whitespace |
| hastscript | MIT | https://github.com/syntax-tree/hastscript |
| highlight.js | BSD-3-Clause | https://github.com/highlightjs/highlight.js |
| highlightjs-vue | CC0-1.0 | https://github.com/highlightjs/highlightjs-vue |
| html-url-attributes | MIT | https://github.com/rehypejs/rehype-minify.git#main |
| inline-style-parser | MIT | https://github.com/remarkablemark/inline-style-parser |
| is-alphabetical | MIT | https://github.com/wooorm/is-alphabetical |
| is-alphanumerical | MIT | https://github.com/wooorm/is-alphanumerical |
| is-decimal | MIT | https://github.com/wooorm/is-decimal |
| is-hexadecimal | MIT | https://github.com/wooorm/is-hexadecimal |
| is-plain-obj | MIT | https://github.com/sindresorhus/is-plain-obj |
| long | Apache-2.0 | https://github.com/dcodeIO/long.js |
| longest-streak | MIT | https://github.com/wooorm/longest-streak |
| lowlight | MIT | https://github.com/wooorm/lowlight |
| lz-string | MIT | https://github.com/pieroxy/lz-string |
| markdown-table | MIT | https://github.com/wooorm/markdown-table |
| mdast-util-find-and-replace | MIT | https://github.com/syntax-tree/mdast-util-find-and-replace |
| mdast-util-from-markdown | MIT | https://github.com/syntax-tree/mdast-util-from-markdown |
| mdast-util-gfm-autolink-literal | MIT | https://github.com/syntax-tree/mdast-util-gfm-autolink-literal |
| mdast-util-gfm-footnote | MIT | https://github.com/syntax-tree/mdast-util-gfm-footnote |
| mdast-util-gfm-strikethrough | MIT | https://github.com/syntax-tree/mdast-util-gfm-strikethrough |
| mdast-util-gfm-table | MIT | https://github.com/syntax-tree/mdast-util-gfm-table |
| mdast-util-gfm-task-list-item | MIT | https://github.com/syntax-tree/mdast-util-gfm-task-list-item |
| mdast-util-gfm | MIT | https://github.com/syntax-tree/mdast-util-gfm |
| mdast-util-mdx-expression | MIT | https://github.com/syntax-tree/mdast-util-mdx-expression |
| mdast-util-mdx-jsx | MIT | https://github.com/syntax-tree/mdast-util-mdx-jsx |
| mdast-util-mdxjs-esm | MIT | https://github.com/syntax-tree/mdast-util-mdxjs-esm |
| mdast-util-phrasing | MIT | https://github.com/syntax-tree/mdast-util-phrasing |
| mdast-util-to-hast | MIT | https://github.com/syntax-tree/mdast-util-to-hast |
| mdast-util-to-markdown | MIT | https://github.com/syntax-tree/mdast-util-to-markdown |
| mdast-util-to-string | MIT | https://github.com/syntax-tree/mdast-util-to-string |
| micromark-core-commonmark | MIT | https://github.com/micromark/micromark.git#main |
| micromark-extension-gfm-autolink-literal | MIT | https://github.com/micromark/micromark-extension-gfm-autolink-literal |
| micromark-extension-gfm-footnote | MIT | https://github.com/micromark/micromark-extension-gfm-footnote |
| micromark-extension-gfm-strikethrough | MIT | https://github.com/micromark/micromark-extension-gfm-strikethrough |
| micromark-extension-gfm-table | MIT | https://github.com/micromark/micromark-extension-gfm-table |
| micromark-extension-gfm-tagfilter | MIT | https://github.com/micromark/micromark-extension-gfm-tagfilter |
| micromark-extension-gfm-task-list-item | MIT | https://github.com/micromark/micromark-extension-gfm-task-list-item |
| micromark-extension-gfm | MIT | https://github.com/micromark/micromark-extension-gfm |
| micromark-factory-destination | MIT | https://github.com/micromark/micromark.git#main |
| micromark-factory-label | MIT | https://github.com/micromark/micromark.git#main |
| micromark-factory-space | MIT | https://github.com/micromark/micromark.git#main |
| micromark-factory-title | MIT | https://github.com/micromark/micromark.git#main |
| micromark-factory-whitespace | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-character | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-chunked | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-classify-character | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-combine-extensions | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-decode-numeric-character-reference | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-decode-string | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-encode | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-html-tag-name | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-normalize-identifier | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-resolve-all | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-sanitize-uri | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-subtokenize | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-symbol | MIT | https://github.com/micromark/micromark.git#main |
| micromark-util-types | MIT | https://github.com/micromark/micromark.git#main |
| micromark | MIT | https://github.com/micromark/micromark.git#main |
| ms | MIT | https://github.com/vercel/ms |
| onnxruntime-common | MIT | https://github.com/Microsoft/onnxruntime |
| onnxruntime-web | MIT | https://github.com/Microsoft/onnxruntime |
| parse-entities | MIT | https://github.com/wooorm/parse-entities |
| platform | MIT | https://github.com/bestiejs/platform.js |
| prismjs | MIT | https://github.com/PrismJS/prism |
| property-information | MIT | https://github.com/wooorm/property-information |
| protobufjs | BSD-3-Clause | https://github.com/protobufjs/protobuf.js |
| react-dom | MIT | https://github.com/facebook/react |
| react-markdown | MIT | https://github.com/remarkjs/react-markdown |
| react-syntax-highlighter | MIT | https://github.com/react-syntax-highlighter/react-syntax-highlighter |
| react | MIT | https://github.com/facebook/react |
| refractor | MIT | https://github.com/wooorm/refractor |
| remark-gfm | MIT | https://github.com/remarkjs/remark-gfm |
| remark-parse | MIT | https://github.com/remarkjs/remark.git#main |
| remark-rehype | MIT | https://github.com/remarkjs/remark-rehype |
| remark-stringify | MIT | https://github.com/remarkjs/remark.git#main |
| scheduler | MIT | https://github.com/facebook/react |
| space-separated-tokens | MIT | https://github.com/wooorm/space-separated-tokens |
| stringify-entities | MIT | https://github.com/wooorm/stringify-entities |
| style-to-js | MIT | https://github.com/remarkablemark/style-to-js |
| style-to-object | MIT | https://github.com/remarkablemark/style-to-object |
| trim-lines | MIT | https://github.com/wooorm/trim-lines |
| trough | MIT | https://github.com/wooorm/trough |
| undici-types | MIT | https://github.com/nodejs/undici |
| unified | MIT | https://github.com/unifiedjs/unified |
| unist-util-is | MIT | https://github.com/syntax-tree/unist-util-is |
| unist-util-position | MIT | https://github.com/syntax-tree/unist-util-position |
| unist-util-stringify-position | MIT | https://github.com/syntax-tree/unist-util-stringify-position |
| unist-util-visit-parents | MIT | https://github.com/syntax-tree/unist-util-visit-parents |
| unist-util-visit | MIT | https://github.com/syntax-tree/unist-util-visit |
| vfile-message | MIT | https://github.com/vfile/vfile-message |
| vfile | MIT | https://github.com/vfile/vfile |
| zwitch | MIT | https://github.com/wooorm/zwitch |

## Voice call (optional backend) dependencies

`uv sync --extra voice-call` で入れた時だけ加わる部品 (= iPhone の app との声の会話、 `backend/voice_call/`)。 上の Backend の表に在る物は除く。

| Package | License | URL |
|---|---|---|
| aiofiles | Apache Software License | https://github.com/Tinche/aiofiles |
| aioice | BSD-3-Clause | https://github.com/aiortc/aioice |
| aiortc | BSD-3-Clause | https://github.com/aiortc/aiortc |
| av | BSD-3-Clause | https://pyav.basswood-io.com |
| dnspython | ISC | https://www.dnspython.org |
| docopt | MIT License | http://docopt.org |
| docstring_parser | MIT License | https://github.com/rr-/docstring_parser |
| flatbuffers | Apache Software License | https://google.github.io/flatbuffers/ |
| google-crc32c | Apache-2.0 | https://github.com/googleapis/python-crc32c |
| ifaddr | MIT License | https://github.com/pydron/ifaddr |
| jiter | MIT | https://github.com/pydantic/jiter/ |
| llvmlite | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | http://llvmlite.readthedocs.io |
| loguru | MIT License | https://github.com/Delgan/loguru |
| loudness | MIT | https://github.com/iver56/loudness |
| Markdown | BSD-3-Clause | https://Python-Markdown.github.io/ |
| mpmath | BSD License | http://mpmath.org/ |
| num2words | GNU Library or Lesser General Public License (LGPL) | https://github.com/savoirfairelinux/num2words |
| numba | BSD License | https://numba.pydata.org |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| onnxruntime | MIT License | https://onnxruntime.ai |
| openai | Apache-2.0 | https://github.com/openai/openai-python |
| opencv-python-headless | Apache Software License | https://github.com/opencv/opencv-python |
| pillow | MIT-CMU | https://python-pillow.github.io |
| pipecat-ai | BSD-2-Clause | https://pipecat.ai |
| protobuf | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| pyee | MIT License | https://github.com/jfhbrook/pyee |
| pylibsrtp | BSD-3-Clause | https://github.com/aiortc/pylibsrtp |
| pyOpenSSL | Apache Software License | https://pyopenssl.org/ |
| resampy | ISC License (ISCL) | https://github.com/bmcfee/resampy |
| sentencex | MIT | https://github.com/wikimedia/sentencex |
| sniffio | Apache Software License; MIT License | https://github.com/python-trio/sniffio |
| soundfile | BSD License | https://github.com/bastibe/python-soundfile |
| soxr | LGPL-2.1-or-later | https://github.com/dofuuz/python-soxr |
| sympy | BSD License | https://sympy.org |
| wait_for2 | Apache-2.0 | https://github.com/Traktormaster/wait-for2 |

## iOS app (`shell/`) dependencies

iPhone の app を作る時だけ使う部品。 Swift Package Manager と npm が取ってきて app に組み込む (= 本リポには同梱しない。
pipecat-client-ios-small-webrtc だけは、 手を入れた写しを `shell/ios/App/Packages/pipecat-client-ios-small-webrtc/` に
同梱する。 上流の LICENSE を同じ folder に置き、 上流との差分は同じ folder の `CPC-PATCHES.md` に並べる)。 ライセンスの原文 (= WebRTC の特許の許諾を含む) は `shell/ios/App/App/Acknowledgements.txt` にまとめて app に同梱する。

| Package | License | URL |
|---|---|---|
| @capacitor/core / @capacitor/ios / @capacitor/cli (= capacitor-swift-pm) | MIT | https://github.com/ionic-team/capacitor |
| pipecat-client-ios | BSD-2-Clause | https://github.com/pipecat-ai/pipecat-client-ios |
| pipecat-client-ios-small-webrtc (= 1.3.0 の写しに手を入れて同梱) | BSD-2-Clause | https://github.com/pipecat-ai/pipecat-client-ios-small-webrtc |
| WebRTC (= stasel/WebRTC が配る Google WebRTC の build) | BSD-3-Clause + WebRTC Additional IP Rights Grant (= build scripts は BSD-3-Clause) | https://github.com/stasel/WebRTC / https://webrtc.org/support/license |

## External services / processes (not bundled)

以下は backend が **subprocess / HTTP で連携**するだけで、 本リポジトリに バンドル / static link されていない。 GPL の copyleft は別プロセス連携には 波及しない (= FSF GPL FAQ 「プロセス分離は通常 derivative work には当たらない」)。

| Component | License | Maintainer | 関係 |
|---|---|---|---|
| Claude Code CLI | Anthropic Commercial Terms | Anthropic | backend が PTY 経由で subprocess 起動 |
| claude-agent-sdk | MIT | Anthropic | Python dependency (= MCP / tool dispatch 経路) |
| Sunshine | GPL-3.0 | LizardByte | Path B 限定、 HTTP / WebRTC 連携 |
| moonlight-web-stream | GPL-3.0 | MrCreativ3001 | Path B 限定、 ユーザが個別 build した web server を `<iframe src="/moonlight/">` で読み込み (= 本リポは source / binary 非同梱、 iframe は separate document context = aggregation) |
| Moonlight (Game Streaming, native client) | GPL-3.0 | Moonlight Game Streaming Project | **使用しない** (= PWA はブラウザ完結、 native client は経路に居ない) |
| Tailscale | BSD-3-Clause (client) | Tailscale Inc. | tailnet 経由配信、 本リポは tailnet 参加のみ |
| VOICEVOX 互換の音声合成 engine (= VOICEVOX ENGINE / AivisSpeech Engine など) | engine による (= LGPL-3.0 ほか) | 各 engine の作者 | 声の機能を使う時だけ、 backend が HTTP で呼ぶ (= 利用者が別に起動する) |
| whisper.cpp (`whisper-server`) | MIT | The ggml authors | 声の機能で聞き取りを使う時だけ、 backend が HTTP で呼ぶ (= 利用者が別に起動する) |
| Smart Turn v3 の model (`smart-turn-v3.2-cpu.onnx`) | BSD-2-Clause | Daily (= Pipecat) | 利用者が取って置いた file を、 backend が画面へそのまま渡す (= 本リポは同梱しない) |

## Source-code adaptations (= 移植・非依存)

以下は npm / pip 経由の依存でなくコードとしての**移植元**。 該当ファイルにはヘッダ末尾に `Adapted from <upstream>, <license>` を明記してあり、 このセクションは上流の copyright 表示 + license 全文を含めることで attribution を完全形にする (= MIT / BSD 系の要件)。

### clsh

- **上流**: [my-claude-utils/clsh](https://github.com/my-claude-utils/clsh)
- **License**: MIT
- **Copyright**: `Copyright (c) 2026 my-claude-utils`
- **移植先**: 以下 4 file の実装は clsh を移植したもの (= 各 file ヘッダに `Adapted from clsh` 記載)
  - `frontend/src/features/terminal/useTerminal.js` (xterm.js lifecycle)
  - `frontend/src/features/ios-native/useKeyboardState.js`
  - `frontend/src/features/ios-native/OnScreenKeyboard.jsx`
  - `frontend/src/utils/keyboard.js` (key → escape sequence 変換)

MIT License 全文:

```
MIT License

Copyright (c) 2026 my-claude-utils

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### smart-turn

- **上流**: [pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn) (= `inference.py`)
- **License**: BSD-2-Clause
- **Copyright**: `Copyright (c) 2024–2025, Daily`
- **移植先**: model への入力の作り方と、 判定の境目 (= 各 file ヘッダに `Adapted from smart-turn` 記載)
  - `frontend/src/features/voice/turn/smartTurn.js`

BSD 2-Clause License 全文:

```
BSD 2-Clause License

Copyright (c) 2024–2025, Daily

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### pipecat

- **上流**: [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) (= 上流の audio/turn/smart_turn/base_smart_turn.py と audio/vad/vad_analyzer.py)
- **License**: BSD-2-Clause
- **Copyright**: `Copyright (c) 2024–2026, Daily`
- **移植先**: 言い終えの判定に回す流れと、 その既定の時間 (= 各 file ヘッダに `Adapted from pipecat` 記載)
  - `frontend/src/features/voice/turnTaker.js`
  - `frontend/src/features/voice/conversation.js`

BSD 2-Clause License 全文:

```
BSD 2-Clause License

Copyright (c) 2024–2026, Daily

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### transformers

- **上流**: [huggingface/transformers](https://github.com/huggingface/transformers) (= `WhisperFeatureExtractor` と `audio_utils.py`)
- **License**: Apache-2.0 (= 全文は本リポジトリの `LICENSE` と同じ)
- **Copyright**: `Copyright 2018- The Hugging Face team. All rights reserved.`
- **移植先**: Whisper と同じ log-mel の特徴の計算を JavaScript で書き直したもの (= ヘッダに `Adapted from transformers` 記載)
  - `frontend/src/features/voice/turn/whisperFeatures.js`

## Bundled model files

以下は npm package の中に入っている model の file で、 build の出力 (= `dist/assets/voice-<hash>/`) にそのまま写される。

### Silero VAD

- **上流**: [snakers4/silero-vad](https://github.com/snakers4/silero-vad) (= npm の @ricky0123/vad-web が同梱する `silero_vad_v5.onnx`)
- **License**: MIT
- **Copyright**: `Copyright (c) 2020-present Silero Team`

MIT License 全文:

```
MIT License

Copyright (c) 2020-present Silero Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Weak copyleft 説明

**MPL-2.0** (= pywebpush / py-vapid / certifi / pathspec) は file-level weak copyleft。 該当 file 自体を改変した場合のみ改変版を MPL-2.0 で公開する義務があるが、 別 file から import / dynamic link する分には影響しない (= 本リポは import 利用のみで MPL ファイルを改変していない)。

**LGPL** (= num2words / soxr、 それに av が同梱する FFmpeg の library と soundfile が同梱する libsndfile) は、 任意の電話の会話の部品にだけ含まれる。 どれも pip が利用者の環境へ入れ、 Python から動的に読み込む library で、 本リポはこれらを同梱・改変・static link しない。 LGPL の義務 (= 差し替え可能な形で渡す・改変を公開する) が生じるのは、 これらを同梱して配る時だけ。

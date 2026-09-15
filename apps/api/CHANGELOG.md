# Changelog

## [0.2.0](https://github.com/Alquimia-ai/red-teaming/compare/api-v0.1.2...api-v0.2.0) (2026-09-15)


### ⚠ BREAKING CHANGES

* **catalogue:** run specs now use brain instead of kb_ref.

### Features

* **catalogue:** adopt schema v2 and conditional brains ([12c9874](https://github.com/Alquimia-ai/red-teaming/commit/12c98741d4946a398ae4d1a0c1caf247331c2e14))


### Bug Fixes

* **deploy:** include catalogue check corrections ([d73691a](https://github.com/Alquimia-ai/red-teaming/commit/d73691a25477fca717191ef746c56d4eb6105868))
* **deploy:** include schema v2 chart assertion ([207d815](https://github.com/Alquimia-ai/red-teaming/commit/207d815eee8e9b549cd7234aa453e35b62dca3d6))
* **repo:** satisfy catalogue v2 checks ([0ae5040](https://github.com/Alquimia-ai/red-teaming/commit/0ae50409ebb505f88ee50f6e60811b767b308e7e))

## [0.1.2](https://github.com/Alquimia-ai/red-teaming/compare/api-v0.1.1...api-v0.1.2) (2026-09-14)


### Code Refactoring

* **repo:** use runtime type imports and concise documentation ([1116334](https://github.com/Alquimia-ai/red-teaming/commit/1116334c493ea55da7fec7a45a57c285b6f613ed))

## [0.1.1](https://github.com/Alquimia-ai/red-teaming/compare/api-v0.1.0...api-v0.1.1) (2026-09-11)

### Bug Fixes

* **api:** resume frozen requests and replace terminal Kubernetes jobs ([#27](https://github.com/Alquimia-ai/red-teaming/pull/27), [538eac7](https://github.com/Alquimia-ai/red-teaming/commit/538eac73b77274b43a6cb21a2f1c1516480b854c)); fixes #17 and #18.

## 0.1.0 (2026-09-11)


### Features

* **api:** accept, freeze and dispatch runs; publish bundles; derive status ([3b27b46](https://github.com/Alquimia-ai/red-teaming/commit/3b27b46cf3cb02638b6f61d79728d793d42ebe82))
* **api:** list accepted runs and carry the registry credential only for grounded runs ([33bccf2](https://github.com/Alquimia-ai/red-teaming/commit/33bccf24af24304dd6f87dc1a1f355cd969b65a0))


### Bug Fixes

* **api:** report the installed package's version ([5587f25](https://github.com/Alquimia-ai/red-teaming/commit/5587f257b75ad81b17f76c3568fef8b6c1a590db))
* **catalogue:** reserve complete bundles and freeze realism prior identity ([4fe556e](https://github.com/Alquimia-ai/red-teaming/commit/4fe556e8ed16ac313ac1b5c8ef51fac314b12f7a))

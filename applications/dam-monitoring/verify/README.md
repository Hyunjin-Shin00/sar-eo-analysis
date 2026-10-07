# applications/dam-monitoring/verify

결과 재계산 검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_figs.py` | Handoff figures for usoi-dam, rendered directly from MintPy h5 (read-only on source). | HDF5 · 이미지 | PNG 그림 |
| `recompute.py` | Independent re-computation of Usoi Dam SBAS numbers from MintPy h5 (read-only). | HDF5 | JSON |

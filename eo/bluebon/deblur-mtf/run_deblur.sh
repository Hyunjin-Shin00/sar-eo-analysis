#!/bin/bash
# BlueBON MS1(Blue)/MS2(Green)/MS3(Red) L0 blind deblurring
#
#   ./run_deblur.sh kernel     커널 추정 (3밴드 동시, 약 5분)
#   ./run_deblur.sh deconv     추정 커널로 deconv, ALPHAS 스윕 (밴드·alpha당 약 1분)
#   ./run_deblur.sh preview    RGB 미리보기 + alpha 비교 크롭
#
# deconv 는 tile_deconv.py 를 거친다. deconv 바이너리는 단일 스레드이고
# (FFTW 멀티스레드는 플랜이 작아 오히려 느림) 비용이 픽셀 수에 거의 선형이므로,
# 타일을 나눠 코어 수만큼 동시에 돌리는 것이 가장 빠르다.
# 전체이미지 1회 처리 대비 6.5배 빠르고 결과 차이는 max 0.43 DN (0.01%).
set -u

ROOT=/mnt/e/bkchoi/working/debulr
BIN=$ROOT/deblur-l0
IN=$ROOT/input
OUT=$ROOT/output
export LD_LIBRARY_PATH=$ROOT/libs:${LD_LIBRARY_PATH:-}

KS=31           # 커널 사이즈 (홀수). 추정 결과 유효 지지는 약 6px 로 충분한 여유.
ITER=5          # estimate-kernel 스케일별 교대 최적화 반복 횟수
ALPHAS="1000 3000 5000"
TILE=2048
OVERLAP=128

mkdir -p "$OUT/log"

case "${1:-}" in
kernel)
    for b in 1 2 3; do
        (
        echo "[MS$b] estimate-kernel 시작 $(date +%T)"
        "$BIN/estimate-kernel" $KS "$IN/MS${b}_DN_dark_rc_p.tiff" \
            "$OUT/k${KS}_ms${b}_i${ITER}.tif" --iterations $ITER --verbose \
            > "$OUT/log/kernel_ms${b}.log" 2>&1
        echo "[MS$b] estimate-kernel 완료 rc=$? $(date +%T)"
        ) &
    done
    wait
    ;;
deconv)
    for b in 1 2 3; do
        for a in $ALPHAS; do
            echo "[MS$b a=$a] $(date +%T)"
            TILE_TMP=$ROOT/.tiletmp python3 "$ROOT/tile_deconv.py" \
                "$IN/MS${b}_DN_dark_rc_p.tiff" \
                "$OUT/k${KS}_ms${b}_i${ITER}.tif" \
                "$OUT/de_ms${b}_k${KS}_i${ITER}_a${a}.tiff" \
                --alpha=$a --tile=$TILE --overlap=$OVERLAP \
                2>&1 | tee "$OUT/log/deconv_ms${b}_a${a}.log" | grep -v "dataset ="
        done
    done
    ;;
preview)
    python3 "$ROOT/make_rgb.py" orig 2>&1 | grep -v "dataset ="
    for a in $ALPHAS; do
        python3 "$ROOT/make_rgb.py" $a 2>&1 | grep -v "dataset ="
    done
    python3 "$ROOT/make_crop_compare.py" 2>&1 | grep -v "dataset ="
    ;;
*)
    echo "usage: $0 {kernel|deconv|preview}" >&2; exit 1;;
esac

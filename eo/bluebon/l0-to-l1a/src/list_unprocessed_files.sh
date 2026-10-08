#!/bin/bash

LEOP_DIR="<WORK_ROOT>/gdrive/LEOP"
OUTPUT_FILE="<WORK_ROOT>/prep/src/unprocessed_files.txt"

# 출력 파일 초기화
> "$OUTPUT_FILE"

# yymmdd_HHMMSS 패턴의 디렉터리만 처리
for session_dir in "$LEOP_DIR"/[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]; do
    if [ ! -d "$session_dir" ]; then
        continue
    fi

    level1a_dir="$session_dir/level-1A"
    level0_dir="$session_dir/level-0"
    skip_reason=""

    # level-1A와 level-1B 둘 다 있는지 확인
    if [ ! -d "$level1a_dir" ] || [ ! -d "$level0_dir" ]; then
        skip_reason="level-0 또는 level-1A 디렉터리 없음"
    fi

    # level-0 내에 *_gray.tiff 파일이 있는지 확인
    if [ -z "$skip_reason" ] && ! ls "$level0_dir"/*_gray.tiff 1>/dev/null 2>&1; then
        skip_reason="level-0에 *_gray.tiff 파일 없음"
    fi

    # level-1A 내에 bb_l1a-rgb*png 또는 bb_l1a_*.tiff 파일이 있는지 확인
    if [ -z "$skip_reason" ]; then
        has_ms_files=$(ls "$level1a_dir"/bb_l1a-rgb_*.png 2>/dev/null | wc -l)
        has_bb_files=$(ls "$level1a_dir"/bb_l1a_*.tiff 2>/dev/null | wc -l)

        if [ "$has_ms_files" -eq 0 ] && [ "$has_bb_files" -eq 0 ]; then
            skip_reason="level-1A에 bb_l1a-rgb*png 또는 bb_l1a_*.tiff 파일 없음"
        fi
    fi

    # 처리되지 않은 세션인 경우 tiff, png 파일 경로 수집
    if [ -n "$skip_reason" ]; then
        echo "# 미처리 세션: $session_dir ($skip_reason)" >> "$OUTPUT_FILE"

        # 해당 세션 디렉터리 내 모든 tiff, png 파일 찾기
        find "$session_dir" -type f \( -iname "*.tiff" -o -iname "*.tif" -o -iname "*.png" \) >> "$OUTPUT_FILE" 2>/dev/null

        echo "" >> "$OUTPUT_FILE"
    fi
done

# 결과 출력
total_files=$(grep -v "^#" "$OUTPUT_FILE" | grep -v "^$" | wc -l)
echo "완료! 처리되지 않은 tiff/png 파일 수: $total_files"
echo "결과 파일: $OUTPUT_FILE"

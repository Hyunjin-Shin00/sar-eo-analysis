#!/bin/bash

LEOP_DIR="/home/bkchoi/gdrive/LEOP"

# yymmdd_HHMMSS 패턴의 디렉터리만 처리
for session_dir in "$LEOP_DIR"/[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]; do
    if [ ! -d "$session_dir" ]; then
        continue
    fi

    level1a_dir="$session_dir/level-1A"
    level1b_dir="$session_dir/level-1B"

    # level-1A와 level-1B 둘 다 있는지 확인
    if [ ! -d "$level1a_dir" ] || [ ! -d "$level1b_dir" ]; then
        continue
    fi

    # level-1A 내에 *_gray.tiff 파일이 있는지 확인
    if ! ls "$level1a_dir"/*_gray.tiff 1>/dev/null 2>&1; then
        continue
    fi

    # level-1B 내에 MS?_DN_dark_rc_p.tiff 또는 bb_l1b_*.tiff 파일이 있는지 확인
    has_ms_files=$(ls "$level1b_dir"/MS*_DN_dark_rc_p.tiff 2>/dev/null | wc -l)
    has_bb_files=$(ls "$level1b_dir"/bb_l1b_*.tiff 2>/dev/null | wc -l)

    if [ "$has_ms_files" -eq 0 ] && [ "$has_bb_files" -eq 0 ]; then
        continue
    fi

    echo "처리 중: $session_dir"

    # 1. level-1A -> level-0 로 변경
    level0_dir="$session_dir/level-0"
    if [ ! -d "$level0_dir" ]; then
        mv "$level1a_dir" "$level0_dir"
        echo "  level-1A -> level-0"
    fi

    # 2. level-1B -> level-1A 로 변경
    if [ -d "$level1b_dir" ]; then
        mv "$level1b_dir" "$level1a_dir"
        echo "  level-1B -> level-1A"

        # 3. bb_l1b_*.tiff -> bb_l1a_*.tiff 로 파일명 변경
        for f in "$level1a_dir"/bb_l1b_*.tiff; do
            if [ -f "$f" ]; then
                new_name=$(echo "$f" | sed 's/bb_l1b_/bb_l1a_/')
                mv "$f" "$new_name"
                echo "  $(basename "$f") -> $(basename "$new_name")"
            fi
        done
    fi

    echo ""
done

echo "완료!"

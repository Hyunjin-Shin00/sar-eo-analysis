#!/bin/bash
# 프로젝트 정리 스크립트
# macOS 리소스 포크 파일, Python 캐시, 오래된 로그 파일 삭제

echo "🧹 프로젝트 정리 시작..."

# 1. macOS 리소스 포크 파일 삭제 (venv 제외, .git 포함)
echo "1️⃣ macOS 리소스 포크 파일 (._*) 삭제 중..."
find . -name "._*" -type f ! -path "./venv/*" -delete
echo "   ✅ 완료"

# 2. Python 캐시 파일 삭제 (venv 제외)
echo "2️⃣ Python 캐시 파일 (__pycache__) 삭제 중..."
find . -type d -name "__pycache__" ! -path "./venv/*" ! -path "./.git/*" -exec rm -rf {} + 2>/dev/null
echo "   ✅ 완료"

# 3. 배치 로그 파일 정리 (최근 5개만 보관)
echo "3️⃣ 배치 로그 파일 정리 중..."
if [ -d "batch_logs" ]; then
    cd batch_logs
    # 최근 5개를 제외한 나머지 삭제
    ls -t *.log 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
    cd ..
    echo "   ✅ 완료 (최근 5개만 보관)"
else
    echo "   ⚠️ batch_logs 디렉토리가 없습니다"
fi

# 4. 기타 로그 파일 삭제
echo "4️⃣ 기타 로그 파일 삭제 중..."
rm -f pipeline_output.log 2>/dev/null
echo "   ✅ 완료"

echo ""
echo "✨ 프로젝트 정리 완료!"
echo ""
echo "📊 정리 결과:"
echo "   - macOS 리소스 포크 파일: 삭제됨"
echo "   - Python 캐시 파일: 삭제됨"
echo "   - 배치 로그: 최근 5개만 보관"
echo "   - 기타 로그: 삭제됨"


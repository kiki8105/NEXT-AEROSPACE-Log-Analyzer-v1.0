# PX4 Log Platform v1.4 배포 가이드

## 1. 배포 파일
- 단일 실행파일: `dist/PX4_Log_Platform_v1.4.exe`
- 메일 전송 권장본: `dist/PX4_Log_Platform_v1.4_portable.zip`

## 2. 팀원 실행 방법
1. `PX4_Log_Platform_v1.4_portable.zip` 압축 해제
2. `PX4_Log_Platform_v1.4.exe` 실행
3. SmartScreen 경고가 나오면:
   - `추가 정보` -> `실행`

## 3. "exe만 메일로 보내도 되나요?"
- **대부분 가능**합니다.
- 다만 아래 조건에서 제한이 생길 수 있습니다:
  - 회사 보안 정책(메일에서 `.exe` 차단)
  - 대상 PC의 OpenGL/GPU 드라이버 이슈
  - Visual C++ 런타임 누락
  - SmartScreen/백신 정책

## 4. 제한 없이(최대한) 안정 배포하려면
완전 100% 보장은 어렵지만, 아래를 적용하면 거의 대부분 환경에서 안정 동작합니다.

### A. 배포 형식
- `.exe` 단일 파일보다 **`.zip` 압축본** 배포 권장
- 사내 공용 저장소(사내 NAS/SharePoint/GitHub Release) 배포 권장

### B. 필수 런타임
- 대상 PC에 **Microsoft Visual C++ 2015-2022 Redistributable (x64)** 설치

### C. 그래픽/OpenGL 호환성
- 3D Path에서 GPU/OpenGL 이슈가 있으면 소프트웨어 렌더링으로 실행:

```bat
set QT_OPENGL=software
PX4_Log_Platform_v1.4.exe
```

- 위 방식은 느려질 수 있지만 호환성은 크게 올라갑니다.

### D. 보안 경고 최소화
- 코드 서명(Code Signing) 인증서로 exe 서명
- 서명된 파일 배포 시 SmartScreen 경고가 크게 줄어듭니다.

### E. 빌드 표준화
- 배포용 빌드는 항상 동일한 환경에서 생성:
  - 동일 Python 버전
  - 동일 dependency 버전
  - 동일 PyInstaller 옵션

## 5. 권장 배포 체크리스트
- [ ] `PX4_Log_Platform_v1.4.exe` 실행 확인
- [ ] 샘플 `.ulg` 로드 확인
- [ ] 2D/3D Path 생성 확인
- [ ] CSV Export 확인
- [ ] SmartScreen/백신 예외 정책 확인

## 6. 빌드 명령(참고)
```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name PX4_Log_Platform_v1.4 `
  --icon "Logo (2).ico" `
  "src/gui/main_window.py"
```

## 7. 장애 대응 빠른 가이드
- 실행 직후 종료: VC++ 재배포 패키지 설치 후 재시도
- 3D 화면 비정상: GPU 드라이버 업데이트 또는 `QT_OPENGL=software` 적용
- 메일 전송 불가: `.zip`으로 압축 후 전송 또는 사내 파일 서버 공유


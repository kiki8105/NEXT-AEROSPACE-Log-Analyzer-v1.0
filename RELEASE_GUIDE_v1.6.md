# NEXT AEROSPACE Log Analyzer v1.6 배포 가이드

## 목차
1. 개요
2. 배포 파일
3. 필수 런타임 및 요구제원
4. 설치 및 실행 방법
5. 최초 실행 체크리스트
6. 기본 사용 매뉴얼
7. 문제 해결 가이드
8. 팀 배포 권장 방식
9. 빌드 재현 명령

## 1. 개요
- 프로그램명: `NEXT AEROSPACE Log Analyzer`
- 버전: `v1.6`
- 목적: PX4/UAV 비행 로그(`.ulg`)를 빠르게 시각화하고 2D/3D Path, CSV Export, 통계 분석을 수행

## 2. 배포 파일
- 실행 파일(One-file): `dist/PX4_Log_Platform_v1.6.exe`
- 메일/메신저 전송 권장본: `dist/PX4_Log_Platform_v1.6.zip`

권장: 팀 배포 시 exe 단독보다 zip으로 전달하세요.

## 3. 필수 런타임 및 요구제원
### 공통 필수
- 운영체제: Windows 10/11 64-bit
- Microsoft Visual C++ 2015-2022 Redistributable (x64)
- 그래픽 드라이버 최신 버전 권장 (OpenGL 사용)

### 권장 하드웨어 (노트북/데스크탑)
- CPU: Intel i5 10세대 / Ryzen 5 3세대 이상
- RAM: 최소 8GB, 권장 16GB 이상
- 저장공간: 최소 2GB 여유(로그/캐시/임시파일 포함)
- GPU: OpenGL 3.x 이상 지원 그래픽

### 대용량 로그 권장
- RAM 16GB 이상
- NVMe SSD 권장
- 외장 그래픽 또는 최신 내장 그래픽 권장

## 4. 설치 및 실행 방법
1. `PX4_Log_Platform_v1.6.zip` 압축 해제
2. `PX4_Log_Platform_v1.6.exe` 실행
3. SmartScreen 경고가 나오면
   - `추가 정보` -> `실행` 선택

## 5. 최초 실행 체크리스트
1. 프로그램 상단 제목이 `NEXT AEROSPACE Log Analyzer`로 표시되는지 확인
2. `.ulg` 파일 드래그 앤 드롭 업로드 확인
3. 트리에서 신호를 그래프로 드래그 앤 드롭 가능한지 확인
4. `Tools -> Flight Path -> 2D Path / 3D Path` 동작 확인
5. CSV Export 생성 및 파일 저장 확인

## 6. 기본 사용 매뉴얼
### 6.1 로그 업로드
- 좌측 업로드 박스에 `.ulg` 파일을 드래그 앤 드롭
- 좌측 트리에 `파일명 | 기체 타입`이 표시되는지 확인

### 6.2 그래프 생성
- 트리 신호를 분석창으로 드래그 앤 드롭
- 다중 선택: `Ctrl + 클릭`, 범위 선택: `Shift + 클릭`

### 6.3 2D/3D Path 생성
- 자동: `x/y` 또는 `x/y/z` 신호 우클릭 드래그 드롭
- 수동: `Tools -> Flight Path -> 2D Path` 또는 `3D Path`

### 6.4 CSV Export
- 좌측 `CSV Export` 버튼 클릭
- 현재 분석창에 표시된 신호를 CSV로 저장

### 6.5 화면 조작
- 우클릭 메뉴: 통계, Auto Fit View, 선 색/스타일/두께
- 타임라인으로 구간/현재 시간 이동

## 7. 문제 해결 가이드
### 7.1 실행이 안 됨
- VC++ Redistributable(x64) 재설치 후 재실행

### 7.2 3D Path가 느리거나 표시 이상
- 그래픽 드라이버 업데이트
- 필요 시 소프트웨어 렌더링으로 실행:
```bat
set QT_OPENGL=software
PX4_Log_Platform_v1.6.exe
```

### 7.3 메일 첨부 차단
- `.exe` 대신 `.zip`으로 전달
- 사내 공유 드라이브/릴리즈 저장소 배포 권장

## 8. 팀 배포 권장 방식
- 1순위: 사내 파일 서버/NAS/SharePoint에 zip 업로드
- 2순위: GitHub Release에 버전별 아카이브 등록
- 권장 포함물:
  - `PX4_Log_Platform_v1.6.zip`
  - `RELEASE_GUIDE_v1.6.md`
  - 변경 내역 요약

## 9. 빌드 재현 명령
```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name "PX4_Log_Platform_v1.6" `
  --icon "c:\Users\rldnd\Desktop\로그분석툴 개발\Logo_main.ico" `
  --add-data "c:\Users\rldnd\Desktop\로그분석툴 개발\Logo_main.ico;." `
  --add-data "c:\Users\rldnd\Desktop\로그분석툴 개발\Logo.ico;." `
  "src/gui/main_window.py"
```

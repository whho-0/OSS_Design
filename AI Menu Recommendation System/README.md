# AI Menu Recommendation System

## 주요 기능

- 회원가입 / 로그인
- 건강 정보 저장
- 단계별 음식 선호 입력
- AI 기반 메뉴 추천 (ex. 간단한 메뉴 추천)
- 추천 기록 저장 및 불러오기

---

## 프로젝트 구조

```plaintext
project/
├── app.py
├── requirements.txt
├── .env
├── .gitignore
├── templates/
│   └── index.html
└── menu_bot.db
```

---

## Local에서 실행 방법

기본적으로는 배포된 웹사이트 링크를 통해 바로 사용할 수 있습니다.

다만, 프로젝트를 직접 실행하거나 수정해보고 싶은 경우 아래 방법으로 로컬 환경에서 실행할 수 있습니다.



---
### 1. 프로젝트 파일 다운로드

GitHub에서 프로젝트를 다운로드하거나 clone 합니다.

```bash
git clone <repository_url>
```

또는 GitHub에서 ZIP 파일 다운로드 후 압축 해제.

---

### 2. 프로젝트 폴더로 이동

터미널(cmd, PowerShell 등)을 열고 프로젝트 폴더로 이동합니다.

```bash
cd project
```

---

### 3. Python 설치 확인

아래 명령어로 Python이 설치되어 있는지 확인합니다.

```bash
python --version
```

또는

```bash
python3 --version
```

Python 3.10 이상 권장.

---

### 4. 필요한 라이브러리 설치

프로젝트에 필요한 패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

---

### 5. `.env` 파일 생성

프로젝트 루트 디렉토리에 `.env` 파일을 생성한 뒤 아래 내용을 입력합니다.

```env
OPENAI_API_KEY=your_api_key
SECRET_KEY=your_secret_key
```

---

### 6. 프로그램 실행

아래 명령어를 실행합니다.

```bash
python app.py
```

또는 환경에 따라:

```bash
python3 app.py
```

---

# HƯỚNG DẪN CÀI ĐẶT DỰ ÁN TRÊN MÁY TÍNH MỚI (SETUP GUIDE)

Tài liệu này hướng dẫn chi tiết từng bước để thiết lập môi trường và chạy dự án **Minervini SEPA Analyzer** khi tải mã nguồn từ GitHub về một máy tính mới (hỗ trợ cả **Windows**, **macOS** và **Linux**).

---

## 📋 Tóm Tắt Quy Trình 5 Bước Cơ Bản

```
1. Clone code từ GitHub
   └── 2. Tạo môi trường ảo (.venv)
        └── 3. Cài thư viện (pip install -r requirements.txt)
             └── 4. Chạy ứng dụng (python app.py)
                  └── 5. Cấu hình Git để code & push tiếp
```

---

## BƯỚC 1: Cài Đặt Công Cụ Nền Tảng (Prerequisites)

Nếu máy tính mới chưa có, hãy tải và cài đặt 2 công cụ sau:

1. **Git**: Tải tại [git-scm.com](https://git-scm.com/).
2. **Python**: Khuyến nghị phiên bản **Python 3.11** hoặc **Python 3.12** tại [python.org](https://www.python.org/).
   > ⚠️ **LƯU Ý TRÊN WINDOWS**: Trong quá trình cài đặt Python, **bắt buộc phải tích chọn ô checkbox**:  
   > `☑ Add python.exe to PATH` (hoặc `Add Python to environment variables`).

---

## BƯỚC 2: Tải Mã Nguồn Từ GitHub Về Máy Mới

Mở Terminal (macOS/Linux) hoặc PowerShell / CMD (Windows) tại thư mục bạn muốn chứa dự án:

```bash
git clone https://github.com/tainguyentantai-oss/minervini-sepa-analyzer.git
cd minervini-sepa-analyzer
```

---

## BƯỚC 3: Tạo Và Kích Hoạt Môi Trường Ảo (Virtual Environment)

Môi trường ảo `.venv` giúp tách biệt các thư viện của dự án, tránh xung đột với các ứng dụng Python khác trên máy:

### 🍏 Trên macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 🪟 Trên Windows (PowerShell hoặc CMD):
```powershell
python -m venv .venv
.venv\Scripts\activate
```

> 💡 **Khắc phục sự cố trên Windows PowerShell**:  
> Nếu gặp thông báo lỗi: `File ... cannot be loaded because running scripts is disabled on this system (PSSecurityException)`:  
> Hãy mở PowerShell và chạy lệnh sau (chọn `Y` khi được hỏi):
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Sau đó chạy lại lệnh kích hoạt: `.venv\Scripts\activate`

Khi kích hoạt thành công, đầu dòng lệnh sẽ xuất hiện chữ `(.venv)`.

---

## BƯỚC 4: Cài Đặt Các Thư Viện Cần Thiết

Chạy lệnh sau để tự động cài đặt toàn bộ các gói (FastAPI, DuckDB, Pandas, APScheduler, v.v.):

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## BƯỚC 5: Khởi Chạy Ứng Dụng & Cập Nhật Dữ Liệu

Dự án được tích hợp cơ chế **tự động khởi tạo cấu trúc CSDL DuckDB** (`data/stock_data.duckdb`) khi chạy lần đầu, không cần cài đặt thêm phần mềm cơ sở dữ liệu ngoài.

### 1. Khởi động Web App:
```bash
python app.py
```
*(Hoặc dùng: `uvicorn app:app --host 127.0.0.1 --port 8000 --reload`)*

### 2. Mở trình duyệt:
Truy cập địa chỉ: **`http://127.0.0.1:8000`**

### 3. Cập nhật dữ liệu chứng khoán lần đầu:
- **Cách 1 (Nhanh nhất):** Gõ mã cổ phiếu bạn quan tâm (ví dụ: `FPT`, `HPG`, `MWG`) vào ô tìm kiếm trên Web, hệ thống sẽ tự động kéo 5 năm lịch sử nến và thông tin CTCK từ API trực tuyến về máy.
- **Cách 2:** Bấm vào biểu tượng **Sync (Làm mới)** ở góc trên thanh tìm kiếm để cập nhật dữ liệu toàn thị trường.
- **Cách 3 (Bằng dòng lệnh):**
  ```bash
  python scheduler/daily_update.py
  ```

---

## BƯỚC 6: Cấu Hình Git Để Tiếp Tục Code & Push Lên GitHub / Vercel

Để khi sửa mã nguồn trên máy mới, bạn có thể thực hiện `git push` trực tiếp (tự động kích hoạt deploy lên Vercel):

### 1. Khai báo danh tính Git:
```bash
git config user.name "tainguyentantai-oss"
git config user.email "tainguyentantai@users.noreply.github.com"
```

### 2. Xác thực tài khoản GitHub:
Khi bạn gõ lệnh `git push origin main` lần đầu, Git sẽ yêu cầu xác thực:
- **Username:** `tainguyentantai-oss`
- **Password:** Dùng **Personal Access Token (Classic)** của GitHub (dạng `ghp_...`), **không dùng mật khẩu thông thường của tài khoản**.

### 3. Lưu thông tin đăng nhập tự động (không cần nhập lại lần sau):
- **Trên Windows:**
  ```bash
  git config --global credential.helper manager
  ```
- **Trên macOS:**
  ```bash
  git config --global credential.helper osxkeychain
  ```
- **Trên Linux:**
  ```bash
  git config --global credential.helper store
  ```

---

## 🚀 Lưu Ý Về Tự Động Hóa (Vercel CI/CD)
Mọi thay đổi khi được đẩy lên nhánh `main` (`git push origin main`) sẽ được Vercel tự động nhận diện và cập nhật trực tiếp lên trang:
👉 **[https://minervini-sepa-analyzer.vercel.app](https://minervini-sepa-analyzer.vercel.app)**

---
title: Minervini SEPA Analyzer
emoji: 📈
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Minervini SEPA Analyzer (Vietnam Stock Market)

Hệ thống phân tích kỹ thuật và tài chính cơ bản chuẩn **SEPA (Specific Order Execution Method)** của **Mark Minervini** và **CANSLIM** dành cho thị trường chứng khoán Việt Nam (HOSE, HNX).

---

## 🚀 Tính Năng Chính

1. **Bộ lọc Trend Template (8/8 Tiêu chí Mark Minervini)**:
   - Giá > MA50, MA150, MA200.
   - MA150 > MA200.
   - MA200 dốc lên $\ge 1$ tháng.
   - MA50 > MA150 & MA200.
   - Giá > MA50.
   - Giá cách đỉnh 52 tuần $\le 25\%$.
   - Giá tăng từ đáy 52 tuần $\ge 25\%$.
   - RS Rating $\ge 70$.

2. **Chỉ số Sức Mạnh Giá Tương Đối (RS Rating 1–99)**:
   - Tính toán theo chuẩn Investor's Business Daily (IBD) với trọng số:
     $$\text{Score} = 40\% \times Q_1 + 20\% \times Q_2 + 20\% \times Q_3 + 20\% \times Q_4$$
   - Xếp hạng phân vị (percentile) từ 1 đến 99 trên toàn bộ thị trường.

3. **Biểu đồ Kỹ thuật TradingView (Lightweight Charts)**:
   - Nến Nhật (Candlestick) + Cột khối lượng (Volume).
   - Tự động gắn nhãn điểm mua: **Điểm mua Pivot (Vol +50%)** và **Breakout VCP**.

4. **Báo cáo Tài chính Tóm tắt (FA)**:
   - Tăng trưởng EPS (YoY) quý gần nhất (> 25%).
   - Tăng trưởng Doanh thu (YoY).
   - Biên lợi nhuận gộp (Gross Margin).
   - Tỷ suất sinh lời trên vốn chủ sở hữu (ROE).

5. **Bộ Lập Lịch Tự Động Hóa (Automation Scheduler)**:
   - Tự động cập nhật nến EOD và tính toán lại RS Rating vào **15:30 các ngày giao dịch từ Thứ 2 đến Thứ 6** (sau khi kết thúc phiên ATC).

---

## 🛠 Cấu Trúc Dự Án

```
Stock/
├── .venv/                     # Môi trường ảo Python 3.12 hiện đại nhất
├── requirements.txt           # Danh sách thư viện
├── app.py                     # Máy chủ Web FastAPI & APScheduler
├── engine/
│   ├── fetcher.py             # Module lấy dữ liệu nến EOD & BCTC
│   ├── minervini.py           # Thuật toán kiểm tra 8 tiêu chí Trend Template & Pivot
│   ├── rs_rating.py           # Thuật toán tính RS Rating (1-99)
│   └── storage.py             # CSDL DuckDB lưu trữ dữ liệu cục bộ
├── scheduler/
│   └── daily_update.py        # Script chạy cập nhật nến toàn thị trường
├── templates/
│   └── index.html             # Giao diện Mini Web (Dark theme chuẩn mockup)
└── data/
    └── stock_data.duckdb      # Cơ sở dữ liệu DuckDB
```

---

## 💻 Hướng Dẫn Sử Dụng

### 1. Khởi động Web App
```bash
.venv/bin/python app.py
```
Sau đó mở trình duyệt truy cập: **`http://127.0.0.1:8000`**

### 2. Chạy cập nhật dữ liệu thủ công (hoặc để tự động chạy lúc 15:30)
```bash
.venv/bin/python scheduler/daily_update.py
```
Hoặc bấm trực tiếp vào biểu tượng **Sync/Làm mới** ở góc trên bên phải thanh tìm kiếm trên Web.

---

## 🖥️ Hướng Dẫn Cài Đặt Khi Tải Sang Máy Mới

Nếu bạn clone hoặc tải mã nguồn này sang một máy tính mới (Windows, macOS hoặc Linux), vui lòng xem hướng dẫn chi tiết từng bước từ cài đặt môi trường, tạo `.venv`, cài `requirements.txt` đến cấu hình Git tại file:
👉 **[Xem chi tiết hướng dẫn tại SETUP.md](SETUP.md)**


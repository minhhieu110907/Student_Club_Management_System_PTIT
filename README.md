# Student Club Management System (SCMS V1)

Hệ thống Quản lý Câu lạc bộ Sinh viên (FastAPI + SQLAlchemy 2.x + MySQL 8.4 + Nginx + Vanilla JS).

## 1. Yêu cầu môi trường

- Docker Desktop / Docker Engine hỗ trợ `docker compose` (v2+).
- Không cần cài Python hay MySQL trên máy host để chạy demo.

## 2. Tạo `.env` và secrets

Sao chép file mẫu trước khi chạy lần đầu:

```powershell
Copy-Item .env.example .env
```

Cập nhật các giá trị trong `.env`:
- `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, và mật khẩu tương ứng trong `DATABASE_URL` (host trong `DATABASE_URL` giữ nguyên là `mysql:3306`).
- `SCMS_JWT_SECRET`: chuỗi **32 bytes ngẫu nhiên mã hóa base64url không padding** (ví dụ tạo bằng `python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())"`).
- `SCMS_DEMO_PASSWORD`: mật khẩu dùng cho các tài khoản demo (chỉ dùng cho môi trường demo local).
- Cấu hình demo-only: `SCMS_ENV=demo`, `SCMS_ALLOW_DEMO_SEED=1`, `SCMS_COOKIE_SECURE=false`. Để **tắt demo seed**, đặt `SCMS_ALLOW_DEMO_SEED=0` (khi chạy `SCMS_ENV=production`, seed luôn bị từ chối và `SCMS_COOKIE_SECURE=false` bị chặn).
- Không commit file `.env` lên Git.

## 3. Chạy lần đầu & Migration / Bootstrap

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

Quy trình khởi động tự động:
1. `mysql` khởi động và kiểm tra `SELECT 1`.
2. `bootstrap` chạy một lần duy nhất: chờ MySQL sẵn sàng, chạy `alembic -c alembic.ini upgrade head`, và chạy seed demo nếu `SCMS_ALLOW_DEMO_SEED=1` và chưa có dữ liệu demo (không ghi đè dữ liệu sẵn có khi restart).
3. `api` chỉ khởi động sau khi `bootstrap` hoàn tất và chỉ báo `healthy` khi `GET /api/v1/health/ready` trả `200` (xác nhận kết nối MySQL và đúng revision `20261026_01`).
4. `nginx` mở cổng `http://localhost:8080` và reverse proxy `/api/` sang `api`.

## 4. Demo Login & Chức năng

Mở <http://localhost:8080>:
- **System Admin**: `admin@scms.example.com` (duyệt yêu cầu lập CLB).
- **Student / Club Manager**: `alex@scms.example.com` (Manager của *Robotics Collective*: tạo/xuất bản/hủy sự kiện, duyệt thành viên, xem participants).
- **Student**: `student@scms.example.com` (tạo yêu cầu lập CLB, ứng tuyển vào CLB, đăng ký & hủy đăng ký sự kiện).
- Mật khẩu các tài khoản demo là giá trị `SCMS_DEMO_PASSWORD` trong `.env`.

Kiểm tra nhanh qua Nginx:
- Liveness: `GET http://localhost:8080/api/v1/health/live`
- Readiness (DB + Alembic): `GET http://localhost:8080/api/v1/health/ready`

## 5. Restart & Stop an toàn

- Khởi động lại toàn bộ stack (giữ nguyên dữ liệu trong volume `mysql_data`):
  ```powershell
  docker compose restart
  ```
- Dừng stack mà **không xóa** dữ liệu database:
  ```powershell
  docker compose down
  ```
*(Tuyệt đối không thêm `-v` / `--volumes` nếu muốn giữ dữ liệu).*

## 6. Lỗi cấu hình phổ biến

- **`SCMS_JWT_SECRET` sai định dạng**: phải là base64url unpadded giải mã đủ ít nhất 32 bytes; nếu sai, `api` sẽ fail-closed khi khởi động.
- **Lỗi `403 ORIGIN_NOT_ALLOWED` khi đăng nhập**: kiểm tra `SCMS_AUTH_ALLOWED_ORIGINS` trong `.env` phải khớp chính xác origin trình duyệt đang mở (ví dụ `http://localhost:8080`).
- **Bootstrap báo lỗi `Access denied` hoặc `Unknown database`**: kiểm tra `DATABASE_URL` khớp `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` và host là `mysql:3306`.

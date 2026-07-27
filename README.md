# VNPT HRM Chatbot Service

FastAPI service làm lớp điều phối cho chatbot HRM. Service không truy cập trực
tiếp PostgreSQL của Odoo; dữ liệu HRM chỉ đi qua module
`vnpt_hrm_chatbot_api`.

## Luồng dependency

`FastAPI lifespan` tạo một `httpx.AsyncClient` dùng chung trong `OdooClient`.
Router lấy client từ `app.state` qua dependency injection. Mỗi request đi qua
middleware để nhận hoặc sinh request ID, đo latency và gắn `X-Request-ID` vào
response. Endpoint chat xác thực user bằng context API của Odoo trước khi trả
phản hồi tạm thời.

```text
HTTP request
  -> request ID / logging middleware
  -> validation + router dependency
  -> shared OdooClient
  -> vnpt_hrm_chatbot_api
  -> standardized API envelope
```

Client Odoo dùng connection pooling, keep-alive và timeout connect/read riêng.
Lifespan đóng pool khi ứng dụng dừng.

## Cấu hình

Sao chép `.env.example` thành `.env`, sau đó thay các giá trị cho môi trường
thực tế. Không commit `.env`. API key không được ghi log hoặc trả về response.

## Chạy development server

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m app.main
```

Lệnh trên dùng `APP_HOST`, `APP_PORT` và `APP_DEBUG` từ `.env`.

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m ruff check app tests
```

## API mẫu

```powershell
curl.exe -X POST http://localhost:8000/api/v1/chat `
  -H "Content-Type: application/json" `
  -H "X-Request-ID: demo-request-1" `
  -d '{"message":"Tôi còn bao nhiêu ngày phép?","conversation_id":null,"user_context":{"odoo_user_id":2}}'
```

Response thành công:

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "Question received",
  "data": {
    "conversation_id": "d3d43dee-71d4-4ee2-bbeb-905724e1d921",
    "answer": "Chatbot service đã nhận câu hỏi.",
    "user_context": {
      "user_id": 2,
      "employee_id": 10,
      "company_id": 1,
      "department_id": 4,
      "timezone": "Asia/Ho_Chi_Minh",
      "language": "vi_VN"
    }
  },
  "meta": {
    "request_id": "demo-request-1",
    "timestamp": "2026-07-27T03:00:00Z"
  }
}
```

Phạm vi hiện tại chưa triển khai LLM routing, tool registry, tool selection,
SSE hay LangGraph. Cấu trúc đã chừa điểm mở rộng cho các bước đó.

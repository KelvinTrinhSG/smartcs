# Semantic cache threshold — 2026-10-21

20 paraphrase pairs (should hit), 20 near-miss pairs (must not hit), `text-embedding-3-small`, cosine similarity.

- Paraphrases: min 0.498, median 0.739, max 0.879
- Near misses: min 0.629, median 0.801, **max 0.989**

## Cosine threshold only

| Threshold | Paraphrase recall | False hits (wrong answer served) |
|---|---|---|
| 0.800 | 20.0% | 10 |
| 0.850 | 10.0% | 7 |
| 0.880 | 0.0% | 4 |
| 0.900 | 0.0% | 3 |
| 0.920 | 0.0% | 2 |
| 0.940 | 0.0% | 2 |
| 0.960 | 0.0% | 1 |
| 0.994 | 0.0% | 0 |

## Cosine candidate + gpt-4o-mini verifier (production)

| Candidate threshold | Paraphrase recall | False hits |
|---|---|---|
| 0.50 | 55.0% | 0 |
| 0.60 | 55.0% | 0 |
| 0.65 | 50.0% | 0 |
| 0.70 | 50.0% | 0 |
| 0.75 | 35.0% | 0 |
| 0.80 | 20.0% | 0 |

Verifier disagreements with the label: 8/40

- (same) Hoàn tiền về thẻ tín dụng mất bao lâu? / Trả hàng thì bao lâu tiền về lại thẻ tín dụng?
- (same) Trả góp qua công ty tài chính cần giấy tờ gì? / Làm hồ sơ trả góp Home Credit cần mang theo gì?
- (same) Thời hạn bảo hành được tính từ ngày nào? / Bảo hành bắt đầu tính từ lúc nào?
- (same) Đổi trả chuột hoặc tai nghe có mất phí không? / Trả lại phụ kiện có tốn phí không?
- (same) 1 điểm thành viên đổi được bao nhiêu tiền? / Mỗi điểm tích lũy quy đổi ra bao nhiêu đồng?
- (same) Điểm tích lũy có bị hết hạn không? / Điểm thành viên có thời hạn sử dụng không?
- (same) Muốn lấy hóa đơn VAT thì phải yêu cầu khi nào? / Xuất hóa đơn đỏ thì phải báo trước bao lâu?
- (same) Sinh nhật khách hàng có quà gì không? / Tháng sinh nhật có ưu đãi gì cho thành viên không?

## Closest near misses

| similarity | a | b |
|---|---|---|
| 0.989 | Trả lại laptop đã bóc seal thì mất phí bao nhiêu? | Trả lại laptop chưa bóc seal thì mất phí bao nhiêu? |
| 0.949 | Trả góp thẻ tín dụng kỳ hạn 12 tháng thì phí chuyển đổi bao nhiêu? | Trả góp thẻ tín dụng kỳ hạn 6 tháng thì phí chuyển đổi bao nhiêu? |
| 0.920 | Cửa hàng TechZone ở Hà Nội nằm ở đâu? | Cửa hàng TechZone ở TP.HCM nằm ở đâu? |
| 0.889 | Màn hình máy tính bên shop bảo hành bao lâu? | Chuột máy tính bên shop bảo hành bao lâu? |
| 0.877 | Thành viên hạng Gold được ưu đãi gì? | Thành viên hạng Silver được ưu đãi gì? |
| 0.853 | Đơn 300 nghìn giao về Đà Nẵng thì phí ship bao nhiêu? | Đơn 300 nghìn giao trong TP.HCM thì phí ship bao nhiêu? |

## Paraphrases below the safe threshold

| similarity | a | b |
|---|---|---|
| 0.879 | Điện thoại bị rơi vỡ màn hình có được bảo hành không? | Làm rơi vỡ màn hình điện thoại thì có được bảo hành không? |
| 0.865 | Laptop ASUS Vivobook bảo hành bao lâu? | Mua laptop Asus Vivobook thì được bảo hành mấy tháng vậy shop? |
| 0.841 | Tôi thanh toán bằng ví MoMo được không? | Shop có nhận thanh toán qua MoMo không? |
| 0.828 | Cửa hàng TechZone ở Hà Nội nằm ở đâu? | Địa chỉ chi nhánh Hà Nội của TechZone? |
| 0.788 | Shop có hỗ trợ trả góp 0% không? | Có mua trả góp lãi suất 0% được không? |
| 0.784 | Thời hạn bảo hành được tính từ ngày nào? | Bảo hành bắt đầu tính từ lúc nào? |
| 0.765 | Cửa hàng mở cửa từ mấy giờ đến mấy giờ? | Giờ mở cửa của cửa hàng là khi nào? |
| 0.758 | Cài lại Windows ở shop có mất phí không? | Shop cài lại win có tính tiền không? |
| 0.749 | Nhận hàng có được mở ra kiểm tra trước khi trả tiền không? | Có được kiểm tra hàng trước khi thanh toán không? |
| 0.739 | Hoàn tiền về thẻ tín dụng mất bao lâu? | Trả hàng thì bao lâu tiền về lại thẻ tín dụng? |
| 0.724 | Phí giao hàng của shop là bao nhiêu? | Ship hàng tốn bao nhiêu tiền vậy shop? |
| 0.701 | Laptop ASUS Vivobook bảo hành bao lâu? | laptop asus vivobook bao hanh bao lau |
| 0.657 | Trả góp qua công ty tài chính cần giấy tờ gì? | Làm hồ sơ trả góp Home Credit cần mang theo gì? |
| 0.650 | Điểm tích lũy có bị hết hạn không? | Điểm thành viên có thời hạn sử dụng không? |
| 0.600 | Phí giao hàng của shop là bao nhiêu? | phi ship bao nhieu vay shop |
| 0.587 | 1 điểm thành viên đổi được bao nhiêu tiền? | Mỗi điểm tích lũy quy đổi ra bao nhiêu đồng? |
| 0.572 | Đổi trả chuột hoặc tai nghe có mất phí không? | Trả lại phụ kiện có tốn phí không? |
| 0.543 | Sinh nhật khách hàng có quà gì không? | Tháng sinh nhật có ưu đãi gì cho thành viên không? |
| 0.503 | Muốn lấy hóa đơn VAT thì phải yêu cầu khi nào? | Xuất hóa đơn đỏ thì phải báo trước bao lâu? |
| 0.498 | Laptop của tôi không lên nguồn thì phải làm sao? | Máy tính xách tay bật không lên thì xử lý thế nào? |

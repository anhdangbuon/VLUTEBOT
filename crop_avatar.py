from PIL import Image, ImageDraw

# Mở ảnh gốc
img = Image.open("lucas_avatar.png").convert("RGBA")
width, height = img.size

# Tìm tâm và bán kính vòng tròn màu xanh (khoảng 86% kích thước ảnh để bỏ viền trắng)
radius = int(min(width, height) * 0.43)
center_x, center_y = width // 2, height // 2

# Tạo mặt nạ hình tròn khít vòng xanh
mask = Image.new("L", (width, height), 0)
draw = ImageDraw.Draw(mask)
draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), fill=255)

# Cắt ảnh theo hình tròn khít
result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
result.paste(img, mask=mask)

# Cắt sát vùng viền trong suốt
bbox = result.getbbox()
if bbox:
    result = result.crop(bbox)

# Lưu đè lại file lucas_avatar.png
result.save("lucas_avatar.png", format="PNG")
print("Đã cắt tròn hoàn hảo file lucas_avatar.png!")
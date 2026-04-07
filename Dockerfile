# Railway için optimize Playwright + Node.js image
FROM mcr.microsoft.com/playwright:v1.40.0-jammy

WORKDIR /app

# Önce bağımlılıkları kopyala (cache optimizasyonu)
COPY package*.json ./

# Tüm bağımlılıkları kur
RUN npm ci

# Kaynak kodu kopyala
COPY . .

# TypeScript derle
RUN npm run build

# Port
EXPOSE 3000

# Başlat
CMD ["node", "dist/server.js"]

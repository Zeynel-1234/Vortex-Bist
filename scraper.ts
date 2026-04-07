import { chromium, Browser, Page, BrowserContext } from 'playwright';
import { Horse, Race } from './types';

const TJK_BASE = 'https://mobil.tjk.org';
const PROXY_URL = process.env.PROXY_URL || ''; // WebShare veya başka proxy

// İnsan gibi rastgele bekleme
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const humanDelay = () => sleep(800 + Math.random() * 1200);

// Browser başlat
async function launchBrowser(): Promise<{ browser: Browser; context: BrowserContext }> {
  const launchOptions: any = {
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--user-agent=Mozilla/5.0 (Linux; Android 11; Samsung Galaxy S21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    ],
  };

  if (PROXY_URL) {
    launchOptions.proxy = { server: PROXY_URL };
    console.log('[Playwright] Proxy kullanılıyor:', PROXY_URL);
  }

  const browser = await chromium.launch(launchOptions);

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    userAgent: 'Mozilla/5.0 (Linux; Android 11; Samsung Galaxy S21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    extraHTTPHeaders: {
      'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    },
    // Bot tespitini önle
    javaScriptEnabled: true,
  });

  // WebDriver tespitini kapat
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    (window as any).chrome = { runtime: {} };
  });

  return { browser, context };
}

// Bugünkü yarış programını çek
export async function scrapeTodayProgram(): Promise<Race[]> {
  const { browser, context } = await launchBrowser();
  const page = await context.newPage();

  try {
    console.log('[TJK] Program sayfasına gidiliyor...');
    await page.goto(`${TJK_BASE}/tr/at-yarisi/program`, {
      waitUntil: 'networkidle',
      timeout: 30000,
    });

    await humanDelay();

    // Yarış hipodromlarını listele
    const tracks = await page.evaluate(() => {
      const items: { name: string; url: string }[] = [];
      document.querySelectorAll('a[href*="hipodrom"], .hipodrom-link, .track-item a').forEach(el => {
        const href = (el as HTMLAnchorElement).href;
        const name = el.textContent?.trim() || '';
        if (name && href) items.push({ name, url: href });
      });
      return items;
    });

    console.log(`[TJK] ${tracks.length} hipodrom bulundu`);

    // Eğer direkt koşu listesi varsa
    const races: Race[] = [];

    // Koşu kartlarını bul
    const raceCards = await page.evaluate(() => {
      const cards: any[] = [];
      document.querySelectorAll('.race-card, .kosu-card, [class*="kosu"], [class*="race"]').forEach((el, idx) => {
        cards.push({
          index: idx,
          text: el.textContent?.slice(0, 100),
          href: (el.querySelector('a') as HTMLAnchorElement)?.href,
        });
      });
      return cards;
    });

    console.log(`[TJK] ${raceCards.length} koşu kartı bulundu`);

    // Her koşuya gir
    for (let i = 0; i < Math.min(raceCards.length, 10); i++) {
      const card = raceCards[i];
      if (!card.href) continue;

      try {
        const race = await scrapeRaceDetail(context, card.href, i + 1);
        if (race && race.horses.length > 0) {
          races.push(race);
          console.log(`[TJK] Koşu ${i + 1}: ${race.horses.length} at`);
        }
      } catch (e) {
        console.error(`[TJK] Koşu ${i + 1} hatası:`, e);
      }

      await humanDelay();
    }

    // Eğer koşu bulunamadıysa mobil program sayfasını dene
    if (races.length === 0) {
      console.log('[TJK] Alternatif sayfa deneniyor...');
      const altRaces = await scrapeAlternativePage(context);
      races.push(...altRaces);
    }

    return races;
  } catch (error) {
    console.error('[TJK] Program sayfası hatası:', error);
    return [];
  } finally {
    await browser.close();
  }
}

// Koşu detay sayfası
async function scrapeRaceDetail(context: BrowserContext, url: string, raceNo: number): Promise<Race | null> {
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
    await humanDelay();

    const data = await page.evaluate((no: number) => {
      const horses: any[] = [];

      // At listesi çek
      const rows = document.querySelectorAll('tr[class*="horse"], tr[class*="at"], .horse-row, table tbody tr');

      rows.forEach((row, idx) => {
        const cells = row.querySelectorAll('td');
        if (cells.length < 3) return;

        const horse: any = {
          no: idx + 1,
          name: '',
          rawRow: row.textContent?.trim().slice(0, 200),
        };

        // At adı bul
        const nameEl = row.querySelector('[class*="name"], [class*="ad"], a');
        horse.name = nameEl?.textContent?.trim() || cells[1]?.textContent?.trim() || `At${idx + 1}`;

        // Sıra numarası
        const noText = cells[0]?.textContent?.trim();
        if (noText && !isNaN(parseInt(noText))) {
          horse.no = parseInt(noText);
        }

        // Jokey
        horse.jockeyName = cells[3]?.textContent?.trim() || '';

        // Kilo
        const kiloText = cells[4]?.textContent?.trim() || '';
        const kiloMatch = kiloText.match(/(\d+\.?\d*)/);
        if (kiloMatch) horse.weight = parseFloat(kiloMatch[1]);

        // Son 6Y
        const son6YEl = row.querySelector('[class*="form"], [class*="son"]');
        horse.son6Y = son6YEl?.textContent?.trim() || cells[5]?.textContent?.trim() || '';

        // AGF
        const agfEl = row.querySelector('[class*="agf"]');
        if (agfEl) {
          const agfText = agfEl.textContent?.trim() || '';
          const agfMatch = agfText.match(/(\d+\.?\d*)/);
          if (agfMatch) horse.agf = parseFloat(agfMatch[1]);
        }

        // HP
        const hpEl = row.querySelector('[class*="hp"]');
        if (hpEl) {
          const hpText = hpEl.textContent?.trim() || '';
          const hpMatch = hpText.match(/(\d+\.?\d*)/);
          if (hpMatch) horse.hp = parseFloat(hpMatch[1]);
        }

        // DS bayrağı
        horse.ds = row.innerHTML.toLowerCase().includes(' ds') || 
                   !!row.querySelector('[class*="ds"]');

        if (horse.name && horse.name.length > 1) {
          horses.push(horse);
        }
      });

      // Koşu bilgileri
      const raceInfo = {
        track: document.querySelector('[class*="track"], [class*="hipodrom"], h1, .race-title')?.textContent?.trim() || 'Bilinmiyor',
        distance: 0,
        surface: '',
        time: '',
        date: new Date().toISOString().split('T')[0],
        no,
      };

      const distanceEl = document.querySelector('[class*="distance"], [class*="mesafe"]');
      if (distanceEl) {
        const m = distanceEl.textContent?.match(/(\d{3,4})/);
        if (m) raceInfo.distance = parseInt(m[1]);
      }

      return { horses, raceInfo };
    }, raceNo);

    if (!data || data.horses.length === 0) {
      console.log(`[TJK] ${url} — at bulunamadı, idman tabı deneniyor`);
    }

    // Her at için idman verisini çek
    for (const horse of data.horses) {
      try {
        const idmanData = await scrapeHorseIdman(page, horse.name);
        if (idmanData) {
          horse.idmanTime = idmanData.time;
          horse.idmanGap = idmanData.gap;
        }
      } catch (e) {
        // İdman opsiyonel
      }
    }

    return {
      id: `race_${raceNo}_${Date.now()}`,
      no: raceNo,
      track: data.raceInfo.track,
      date: data.raceInfo.date,
      time: data.raceInfo.time,
      distance: data.raceInfo.distance,
      surface: data.raceInfo.surface,
      horses: data.horses,
      source: 'scraper',
    };
  } catch (error) {
    console.error(`[TJK] Koşu ${raceNo} detay hatası:`, error);
    return null;
  } finally {
    await page.close();
  }
}

// At idman verisi
async function scrapeHorseIdman(page: Page, horseName: string): Promise<{ time: string; gap: number } | null> {
  try {
    // İdman sekmesini bul ve tıkla
    const idmanTab = await page.$('[class*="idman"], [href*="idman"], button:has-text("İdman")');
    if (!idmanTab) return null;

    await idmanTab.click();
    await sleep(1000);

    const idmanData = await page.evaluate((name: string) => {
      // Tablodaki ilk idman kaydını bul
      const rows = document.querySelectorAll('table tbody tr, .idman-row');
      for (const row of rows) {
        const text = row.textContent || '';
        const timeMatch = text.match(/(\d{1,2}:\d{2}\.\d{2}|\d{2}\.\d{2})/);
        if (timeMatch) {
          return { time: timeMatch[1], gap: 0 };
        }
      }
      return null;
    }, horseName);

    return idmanData;
  } catch {
    return null;
  }
}

// Alternatif sayfa (program farklı URL'deyse)
async function scrapeAlternativePage(context: BrowserContext): Promise<Race[]> {
  const page = await context.newPage();
  const races: Race[] = [];

  try {
    // TJK'nın farklı URL yapılarını dene
    const urls = [
      `${TJK_BASE}/tr/at-yarisi/program`,
      `${TJK_BASE}/tr/kosu-program`,
      `https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgram`,
    ];

    for (const url of urls) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
        await humanDelay();

        const pageText = await page.textContent('body') || '';
        if (pageText.length > 500) {
          console.log(`[TJK] ${url} içerik var, parse ediliyor...`);

          // Generic tablo parse
          const tableData = await page.evaluate(() => {
            const rows: any[] = [];
            document.querySelectorAll('tr').forEach(row => {
              const cells = Array.from(row.querySelectorAll('td')).map(td => td.textContent?.trim() || '');
              if (cells.length >= 4 && cells.some(c => c.length > 1)) {
                rows.push(cells);
              }
            });
            return rows;
          });

          if (tableData.length > 5) {
            console.log(`[TJK] ${tableData.length} satır bulundu`);
            // Bu veriyi işle...
          }
          break;
        }
      } catch (e) {
        console.log(`[TJK] ${url} erişilemedi`);
      }
    }
  } finally {
    await page.close();
  }

  return races;
}

// Jokey istatistikleri
export async function scrapeJockeyStats(jockeyId: string): Promise<{ winRate: number } | null> {
  const { browser, context } = await launchBrowser();
  const page = await context.newPage();

  try {
    await page.goto(`${TJK_BASE}/tr/at-yarisi/jokey/${jockeyId}`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });

    const stats = await page.evaluate(() => {
      const text = document.body.textContent || '';
      const winMatch = text.match(/Kazanma[:\s]+%?(\d+\.?\d*)/i);
      if (winMatch) {
        return { winRate: parseFloat(winMatch[1]) / 100 };
      }
      return null;
    });

    return stats;
  } catch {
    return null;
  } finally {
    await browser.close();
  }
}

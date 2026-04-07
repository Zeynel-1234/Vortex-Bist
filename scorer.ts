import { Horse, Race, ScoreResult, ScoreBreakdown, TrinityResult } from './types';

// ============================================================
// URİS v3.5 — Ultra Katmanlı Akıl Sistemi
// 12 Katman | Max 116p (Ham 100p + Bonus 16p)
// ≥80 → Kesin Aday | 70-79 → 2-3. Aday | <70 → İzle
// ============================================================

// Katman 1: Son 6Y analizi (0-25p)
// Son6Y: "1-2-0-3-1-5" → soldan sağa = yeniden eskiye
function scoreSon6Y(son6Y: string | undefined, horses: Horse[]): { score: number; flags: string[] } {
  if (!son6Y || son6Y === '-' || son6Y === '0-0-0-0-0-0') {
    return { score: 5, flags: ['SON6Y_YOK: Yeni at — nötr'] };
  }

  const flags: string[] = [];
  const races = son6Y.split('-').map(r => r.trim());
  const recent = races.slice(0, 3);   // Son 3 koşu (en yeni)
  const older = races.slice(3, 6);    // Eski 3 koşu

  let score = 0;

  // Son 3 koşuya ağırlık ver
  for (let i = 0; i < recent.length; i++) {
    const pos = parseInt(recent[i]) || 99;
    const weight = i === 0 ? 1.5 : i === 1 ? 1.2 : 1.0;
    if (pos === 1) score += 5 * weight;
    else if (pos === 2) score += 4 * weight;
    else if (pos === 3) score += 3 * weight;
    else if (pos <= 5) score += 2 * weight;
    else if (pos === 0) score += 1.5 * weight; // 0 = koşmadı/bilinmiyor
    else score += Math.max(0, 3 - pos) * weight;
  }

  // Eski koşular (daha az ağırlık)
  for (const r of older) {
    const pos = parseInt(r) || 99;
    if (pos === 1) score += 1.5;
    else if (pos === 2) score += 1;
    else if (pos === 3) score += 0.7;
  }

  // Trend: Son koşu kazandıysa bonus
  const lastPos = parseInt(recent[0]) || 99;
  if (lastPos === 1) {
    score += 2;
    flags.push('SON_KOŞU_1.: Form zirvesinde');
  }

  // Tutarlılık bonusu: Son 3 hep ilk 3'te
  const consistentTop3 = recent.every(r => parseInt(r) <= 3 && parseInt(r) > 0);
  if (consistentTop3) {
    score += 2;
    flags.push('TUTARLI_FORM: Son 3 koşu ilk 3');
  }

  // Form yükselişi: Pozisyon iyileşiyor mu?
  const pos0 = parseInt(recent[0]) || 99;
  const pos1 = parseInt(recent[1]) || 99;
  const pos2 = parseInt(recent[2]) || 99;
  if (pos0 < pos1 && pos1 < pos2) {
    score += 1.5;
    flags.push('FORM_YÜKSELİŞİ: Her koşu daha iyi');
  }

  return { score: Math.min(25, Math.round(score)), flags };
}

// Katman 2: Piyasa sinyali AGF/HP (0-15p)
function scorePiyasa(agf: number | undefined, hp: number | undefined, horseCount: number): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  // AGF skoru (ortalama ganyan favori)
  if (agf !== undefined && agf > 0) {
    if (agf <= 1.5) { score += 12; flags.push(`AGF_BÜYÜK_FAVORİ: ${agf}`); }
    else if (agf <= 2.5) { score += 10; flags.push(`AGF_FAVORİ: ${agf}`); }
    else if (agf <= 4) { score += 8; }
    else if (agf <= 7) { score += 5; }
    else if (agf <= 12) { score += 3; }
    else { score += 1; flags.push(`AGF_UZUN: ${agf} — ghost fırsatı`); }
  } else {
    score += 4; // AGF yok → nötr
  }

  // HP sinyali
  if (hp !== undefined && hp > 0) {
    if (hp <= 2) { score += 3; flags.push(`HP_GÜÇLÜ: ${hp}`); }
    else if (hp <= 5) { score += 2; }
    else { score += 1; }
  }

  // Piyasa paradoks: HP << AGF → gizli favori
  if (hp !== undefined && agf !== undefined && hp > 0 && agf > 0) {
    if (hp < agf * 0.5) {
      score += 2;
      flags.push('GİZLİ_FAVORİ: HP çok düşük, piyasa görüyor');
    }
  }

  return { score: Math.min(15, Math.round(score)), flags };
}

// Katman 3: Jokey kalitesi (0-12p)
function scoreJokey(winRate: number | undefined, jockeyName: string | undefined): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  if (winRate === undefined) {
    // İsme göre tahmini değerlendirme (bilinen jokeyler)
    const eliteJockeys = ['parmaksız', 'özen', 'yıldız', 'küçükkaya', 'demircioğlu', 'yıldırım'];
    const goodJockeys = ['güngör', 'karataş', 'ateş', 'avcı', 'çelik'];

    if (jockeyName) {
      const nameLower = jockeyName.toLowerCase();
      if (eliteJockeys.some(j => nameLower.includes(j))) {
        score = 10;
        flags.push(`ELİT_JOKEY: ${jockeyName}`);
      } else if (goodJockeys.some(j => nameLower.includes(j))) {
        score = 7;
      } else {
        score = 5;
      }
    } else {
      score = 4;
    }
  } else {
    if (winRate >= 0.20) { score = 12; flags.push(`JOKEY_%${Math.round(winRate*100)} ÜST DÜZEY`); }
    else if (winRate >= 0.15) { score = 9; flags.push(`JOKEY_%${Math.round(winRate*100)} İYİ`); }
    else if (winRate >= 0.10) { score = 6; }
    else if (winRate >= 0.05) { score = 4; }
    else { score = 2; flags.push('JOKEY_DÜŞÜK_%'); }
  }

  return { score: Math.min(12, score), flags };
}

// Katman 4: Antrenör kalitesi (0-8p)
function scoreAntrenor(winRate: number | undefined): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  if (winRate === undefined) {
    return { score: 3, flags: [] }; // Nötr
  }

  if (winRate >= 0.20) { score = 8; flags.push(`ANTRENÖR_%${Math.round(winRate*100)} ELİT`); }
  else if (winRate >= 0.15) { score = 6; }
  else if (winRate >= 0.10) { score = 4; }
  else if (winRate >= 0.05) { score = 2; }
  else { score = 1; }

  return { score, flags };
}

// Katman 5: Kilo avantajı (0-8p)
function scoreKilo(weight: number | undefined, horses: Horse[]): { score: number; flags: string[] } {
  const flags: string[] = [];

  if (!weight) return { score: 4, flags: [] };

  const weights = horses.map(h => h.weight).filter(w => w !== undefined) as number[];
  if (weights.length === 0) return { score: 4, flags: [] };

  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const avgWeight = weights.reduce((a, b) => a + b, 0) / weights.length;

  let score = 0;

  // Mutlak kilo değerlendirmesi
  if (weight <= 54) { score += 3; flags.push(`KİLO_HAFİF: ${weight}kg`); }
  else if (weight <= 57) { score += 2; }
  else if (weight <= 60) { score += 1; }
  else { flags.push(`KİLO_AĞIR: ${weight}kg`); }

  // Göreli kilo (diğer atlarla karşılaştırma)
  const relativeAdv = avgWeight - weight;
  if (relativeAdv >= 3) { score += 4; flags.push(`GÖRE_EN_HAFİF: ${relativeAdv}kg avantaj`); }
  else if (relativeAdv >= 1) { score += 2; }
  else if (relativeAdv <= -3) { flags.push(`GÖRE_EN_AĞIR: ${Math.abs(relativeAdv)}kg dezavantaj`); }

  return { score: Math.min(8, score), flags };
}

// Katman 6: Form tazeliği / KGS (0-8p)
function scoreKGS(kgs: number | undefined): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  if (kgs === undefined) return { score: 4, flags: [] };

  if (kgs <= 14) { score = 8; flags.push(`TAZE_FORM: ${kgs} gün önce`); }
  else if (kgs <= 21) { score = 6; flags.push(`İYİ_FORM: ${kgs} gün`); }
  else if (kgs <= 30) { score = 5; }
  else if (kgs <= 45) { score = 3; }
  else if (kgs <= 60) { score = 2; flags.push(`UZUN_ARA: ${kgs} gün`); }
  else { score = 1; flags.push(`ÇOK_UZUN_ARA: ${kgs} gün — şüpheli`); }

  // İlk koşu (kgs çok yüksek veya bilinmiyor)
  if (kgs > 180) {
    score = 3;
    flags.push('UZUN_DİNLENME: Antrenman önemli');
  }

  return { score, flags };
}

// Katman 7: İdman kalitesi (0-8p)
function scoreIdman(idmanTime: string | undefined, idmanGap: number | undefined): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  // İdman süresi değerlendirmesi
  if (idmanTime) {
    // Tipik format: "1:14.50" veya "74.50" saniye
    let seconds = 0;
    if (idmanTime.includes(':')) {
      const parts = idmanTime.split(':');
      seconds = parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    } else {
      seconds = parseFloat(idmanTime);
    }

    // 1000m için referans: 65-70 saniye üst düzey
    if (seconds > 0) {
      if (seconds <= 67) { score += 6; flags.push(`İDMAN_SÜPER: ${idmanTime}`); }
      else if (seconds <= 70) { score += 5; flags.push(`İDMAN_İYİ: ${idmanTime}`); }
      else if (seconds <= 74) { score += 3; }
      else if (seconds <= 80) { score += 2; }
      else { score += 1; flags.push(`İDMAN_YAVAŞ: ${idmanTime}`); }
    }
  } else {
    score = 3; // İdman yok → nötr
  }

  // İdman-koşu arası (yakın idman = iyi)
  if (idmanGap !== undefined) {
    if (idmanGap <= 3) { score += 2; flags.push('İDMAN_YAKLAŞIK: Koşuya çok yakın'); }
    else if (idmanGap <= 7) { score += 1; }
  }

  // Kenter sinyali
  if (idmanTime && idmanTime.toLowerCase().includes('k')) {
    score = Math.max(score, 4);
    flags.push('KENTER: Stratejik gizleme olabilir');
  }

  return { score: Math.min(8, score), flags };
}

// Katman 8: DS bayrağı (0-5p)
function scoreDS(ds: boolean | undefined): { score: number; flags: string[] } {
  if (ds) {
    return { score: 5, flags: ['DS_BAYRAĞ: Dereceli spor — kalite kanıtlı'] };
  }
  return { score: 0, flags: [] };
}

// Katman 9-12: Mesafe, Pist, Sahip, Yaş (0-11p)
function scoreOther(horse: Horse, race: Race): { score: number; flags: string[] } {
  const flags: string[] = [];
  let score = 0;

  // Mesafe uyumu (0-4p)
  if (race.distance) {
    const dist = race.distance;
    if (dist <= 1000 && horse.age && horse.age <= 2) { score += 3; flags.push('KISA_GENÇ: Mesafe uyumu iyi'); }
    else if (dist >= 1600) { score += 2; }
    else { score += 1; }
  }

  // Pist uyumu (0-3p)
  if (race.surface && horse.surface) {
    if (race.surface.toLowerCase() === horse.surface.toLowerCase()) {
      score += 3;
      flags.push(`PİST_UYUM: ${race.surface}`);
    }
  }

  // Sahip (0-2p)
  if (horse.ownerName) {
    score += 1; // Bilinen sahip = hafif artı
  }

  // Yaş/kondisyon (0-2p)
  if (horse.age) {
    if (horse.age >= 4 && horse.age <= 6) { score += 2; flags.push('FORM_YAŞI: Peak kondisyon'); }
    else if (horse.age === 3 || horse.age === 7) { score += 1; }
  }

  return { score: Math.min(11, score), flags };
}

// Ghost winner tespiti
// AGF yüksek ama form ve idman güçlü olan atları bul
function detectGhost(scores: ScoreResult[]): ScoreResult | null {
  if (scores.length < 3) return null;

  const sorted = [...scores].sort((a, b) => b.total - a.total);
  const topTwo = sorted.slice(0, 2);

  // Top 2 dışındaki atlara bak
  const others = sorted.slice(2);

  // Ghost kriterleri:
  // - Skor makul (≥60)
  // - AGF yüksek (piyasa görmüyor)
  // - Son 6Y form var
  const ghosts = others.filter(s => {
    const isUnderdog = !s.horse.agf || s.horse.agf > 6;
    const hasForm = s.score >= 60;
    const hasGoodSon6Y = s.horse.son6Y && 
      s.horse.son6Y.split('-').slice(0, 3).some(r => parseInt(r) <= 2);
    return isUnderdog && hasForm && hasGoodSon6Y;
  });

  if (ghosts.length > 0) {
    ghosts[0].flags.push('👻 GHOST: Piyasanın görmediği güçlü aday');
    return ghosts[0];
  }

  // Ghost bulunamazsa en yüksek skorlu undergog
  const underdog = others.find(s => s.score >= 55);
  if (underdog) {
    underdog.flags.push('👻 GHOST: Potansiyel sürpriz');
    return underdog;
  }

  return null;
}

// Ana skorlama fonksiyonu
export function scoreHorse(horse: Horse, race: Race): ScoreResult {
  const flags: string[] = [];

  // 12 Katman
  const l1 = scoreSon6Y(horse.son6Y, race.horses);
  const l2 = scorePiyasa(horse.agf, horse.hp, race.horses.length);
  const l3 = scoreJokey(horse.jockeyWinRate, horse.jockeyName);
  const l4 = scoreAntrenor(horse.trainerWinRate);
  const l5 = scoreKilo(horse.weight, race.horses);
  const l6 = scoreKGS(horse.kgs);
  const l7 = scoreIdman(horse.idmanTime, horse.idmanGap);
  const l8 = scoreDS(horse.ds);
  const l9_12 = scoreOther(horse, race);

  const breakdown: ScoreBreakdown = {
    son6Y: l1.score,
    piyasa: l2.score,
    jokey: l3.score,
    antrenor: l4.score,
    kilo: l5.score,
    kgs: l6.score,
    idman: l7.score,
    ds: l8.score,
    mesafe: Math.min(4, l9_12.score),
    pist: 0,
    sahip: 0,
    yas: 0,
  };

  const hamScore = Object.values(breakdown).reduce((a, b) => a + b, 0);

  // Kategori bonusu (max 16p)
  let bonus = 0;
  const allFlags = [...l1.flags, ...l2.flags, ...l3.flags, ...l4.flags,
                   ...l5.flags, ...l6.flags, ...l7.flags, ...l8.flags, ...l9_12.flags];

  // Bonus 1: Tam form profili
  if (l1.score >= 20 && l3.score >= 9) { bonus += 4; flags.push('⭐ BONUS: Güçlü form + jokey kombinasyonu'); }
  // Bonus 2: Piyasa + form uyumu
  if (l2.score >= 10 && l1.score >= 15) { bonus += 3; flags.push('⭐ BONUS: Piyasa ve form aynı yönde'); }
  // Bonus 3: İdman + taze form
  if (l7.score >= 6 && l6.score >= 7) { bonus += 3; flags.push('⭐ BONUS: Taze idman + taze form'); }
  // Bonus 4: DS + iyi jokey
  if (l8.score > 0 && l3.score >= 7) { bonus += 3; flags.push('⭐ BONUS: DS + kaliteli jokey'); }
  // Bonus 5: Kilo avantajı + AGF
  if (l5.score >= 6 && l2.score >= 8) { bonus += 3; flags.push('⭐ BONUS: Hafif kilo + piyasa desteği'); }

  bonus = Math.min(16, bonus);
  const totalScore = Math.min(116, hamScore + bonus);

  let tier: ScoreResult['tier'];
  if (totalScore >= 80) tier = 'SOVEREIGN';
  else if (totalScore >= 70) tier = 'BREAKER';
  else if (totalScore >= 60) tier = 'GHOST';
  else tier = 'IZLE';

  return {
    horse,
    score: hamScore,
    bonus,
    total: totalScore,
    probability: 0, // Bayesian sonra hesaplanacak
    tier,
    breakdown,
    flags: [...allFlags, ...flags],
  };
}

// Bayesian olasılık hesaplama
function bayesianProbabilities(scores: ScoreResult[]): ScoreResult[] {
  const totalScore = scores.reduce((sum, s) => sum + Math.max(1, s.total), 0);
  return scores.map(s => ({
    ...s,
    probability: Math.round((Math.max(1, s.total) / totalScore) * 100),
  }));
}

// Trinity sistemi — ana fonksiyon
export function analyzRace(race: Race): TrinityResult {
  // Tüm atları skorla
  let scores = race.horses.map(h => scoreHorse(h, race));

  // Bayesian olasılıkları hesapla
  scores = bayesianProbabilities(scores);

  // Skora göre sırala
  const sorted = [...scores].sort((a, b) => b.total - a.total);

  const sovereign = sorted[0];
  const breaker = sorted[1] || sorted[0];

  // Ghost detection
  const ghostResult = detectGhost(scores);
  const ghost = ghostResult || sorted[Math.min(2, sorted.length - 1)];

  // Tier atamaları
  sovereign.tier = 'SOVEREIGN';
  breaker.tier = 'BREAKER';
  if (ghost !== sovereign && ghost !== breaker) ghost.tier = 'GHOST';

  // Analiz metni
  const analysis = generateAnalysis(sovereign, breaker, ghost, race);

  return {
    raceId: race.id,
    raceNo: race.no,
    track: race.track,
    sovereign,
    breaker,
    ghost,
    allScores: sorted,
    analysis,
    timestamp: new Date().toISOString(),
  };
}

function generateAnalysis(
  sovereign: ScoreResult,
  breaker: ScoreResult,
  ghost: ScoreResult,
  race: Race
): string {
  const lines: string[] = [];

  lines.push(`🏇 ${race.track} — ${race.no}. Koşu Analizi`);
  lines.push('');
  lines.push(`👑 SOVEREIGN (${sovereign.horse.name}): ${sovereign.total}p / %${sovereign.probability}`);
  lines.push(`   ↳ ${sovereign.flags.slice(0, 3).join(' | ')}`);
  lines.push('');
  lines.push(`⚔️ BREAKER (${breaker.horse.name}): ${breaker.total}p / %${breaker.probability}`);
  lines.push(`   ↳ ${breaker.flags.slice(0, 2).join(' | ')}`);
  lines.push('');
  lines.push(`👻 GHOST (${ghost.horse.name}): ${ghost.total}p / %${ghost.probability}`);
  lines.push(`   ↳ ${ghost.flags.slice(0, 2).join(' | ')}`);
  lines.push('');

  // Uyarı: Sovereign çok düşükse
  if (sovereign.total < 70) {
    lines.push('⚠️ UYARI: Bu koşuda belirgin favori yok. Sürpriz ihtimali yüksek.');
  }

  if (ghost.flags.some(f => f.includes('GHOST'))) {
    lines.push(`⚡ SÜRPRIZ: ${ghost.horse.name} göz ardı edilmemeli`);
  }

  return lines.join('\n');
}

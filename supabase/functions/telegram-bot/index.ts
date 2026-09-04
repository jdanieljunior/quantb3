import { createClient } from "jsr:@supabase/supabase-js@2";

type TelegramMessage = { chat?: { id?: number }; text?: string };
type TelegramUpdate = { message?: TelegramMessage };
type EquityPoint = { date: string; equity: number; cash: number; pos_value: number; n_positions: number };

const TELEGRAM_API = "https://api.telegram.org";

function env(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`Segredo ${name} não configurado.`);
  return value;
}

function getServiceKey(): string {
  const modernKeys = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (modernKeys) return JSON.parse(modernKeys).default;
  return env("SUPABASE_SERVICE_ROLE_KEY");
}

function brl(value: number | null | undefined): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value ?? 0);
}

function pct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2).replace(".", ",")}%`;
}

function helpText(): string {
  return [
    "🤖 *QuantB3 — comandos disponíveis*",
    "/sinais — sinais e ordens planejadas da semana",
    "/posicoes — posições simuladas atuais",
    "/carteira — patrimônio, caixa e valor investido",
    "/performance — retorno e drawdown",
    "/grafico — curva de patrimônio em imagem",
    "/ajuda — esta mensagem",
  ].join("\n");
}

function svgChart(points: EquityPoint[]): string {
  const width = 900;
  const height = 480;
  const pad = { left: 76, right: 32, top: 58, bottom: 72 };
  const values = points.map((point) => Number(point.equity));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, max * 0.02, 1);
  const low = min - spread * 0.12;
  const high = max + spread * 0.12;
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const x = (index: number) => pad.left + (points.length === 1 ? chartWidth / 2 : index * chartWidth / (points.length - 1));
  const y = (value: number) => pad.top + ((high - value) / (high - low)) * chartHeight;
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(Number(point.equity)).toFixed(1)}`).join(" ");
  const area = `${line} L${x(points.length - 1).toFixed(1)},${(height - pad.bottom).toFixed(1)} L${x(0).toFixed(1)},${(height - pad.bottom).toFixed(1)} Z`;
  const first = values[0];
  const last = values.at(-1) ?? first;
  const ret = ((last / first) - 1) * 100;
  const grid = Array.from({ length: 5 }, (_, index) => {
    const value = low + ((high - low) * index) / 4;
    const yy = y(value).toFixed(1);
    return `<line x1="${pad.left}" x2="${width - pad.right}" y1="${yy}" y2="${yy}" stroke="#24324a"/><text x="${pad.left - 10}" y="${Number(yy) + 4}" text-anchor="end" fill="#9fb0c9" font-size="12">${brl(value)}</text>`;
  }).join("");
  const start = new Date(points[0].date).toLocaleDateString("pt-BR", { timeZone: "UTC" });
  const end = new Date(points.at(-1)!.date).toLocaleDateString("pt-BR", { timeZone: "UTC" });
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <rect width="100%" height="100%" fill="#0b1220" rx="18"/>
  <text x="${pad.left}" y="32" fill="#f8fafc" font-family="Arial, sans-serif" font-size="21" font-weight="700">QuantB3 — Curva de Patrimônio</text>
  <text x="${pad.left}" y="${height - 28}" fill="#9fb0c9" font-family="Arial, sans-serif" font-size="12">${start}</text>
  <text x="${width - pad.right}" y="${height - 28}" text-anchor="end" fill="#9fb0c9" font-family="Arial, sans-serif" font-size="12">${end}</text>
  ${grid}
  <path d="${area}" fill="#38bdf8" opacity="0.12"/>
  <path d="${line}" fill="none" stroke="#38bdf8" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="${x(points.length - 1)}" cy="${y(last)}" r="5" fill="#38bdf8"/>
  <text x="${width - pad.right}" y="32" text-anchor="end" fill="${ret >= 0 ? "#34d399" : "#fb7185"}" font-family="Arial, sans-serif" font-size="18" font-weight="700">${pct(ret)}</text>
</svg>`;
}

async function telegram(token: string, method: string, body: FormData | Record<string, unknown>) {
  const options: RequestInit = body instanceof FormData
    ? { method: "POST", body }
    : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(`${TELEGRAM_API}/bot${token}/${method}`, options);
  if (!response.ok) throw new Error(`Telegram ${method}: ${response.status}`);
}

Deno.serve(async (request) => {
  try {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.searchParams.get("secret") !== env("TELEGRAM_WEBHOOK_SECRET")) {
      return new Response("Not found", { status: 404 });
    }

    const update = await request.json() as TelegramUpdate;
    const chatId = update.message?.chat?.id;
    const command = update.message?.text?.trim().toLowerCase().split(/\s+/)[0]?.split("@")[0];
    if (!chatId || !command) return new Response("ok");
    if (String(chatId) !== env("TELEGRAM_ALLOWED_CHAT_ID")) return new Response("ok");

    const token = env("TELEGRAM_BOT_TOKEN");
    const supabase = createClient(env("SUPABASE_URL"), getServiceKey());
    const sendText = (text: string) => telegram(token, "sendMessage", { chat_id: chatId, text, parse_mode: "Markdown" });

    if (command === "/ajuda" || command === "/start") {
      await sendText(helpText());
    } else if (command === "/sinais") {
      const { data: latest, error: latestError } = await supabase.from("signals").select("signal_date").order("signal_date", { ascending: false }).limit(1);
      if (latestError) throw latestError;
      if (!latest?.[0]) {
        await sendText("Ainda não há sinais gerados.");
      } else {
        const signalDate = latest[0].signal_date;
        const { data, error } = await supabase.from("signals").select("ticker,action,rank,ref_price,stop_price,take_price").eq("signal_date", signalDate).order("rank");
        if (error) throw error;
        const lines = (data ?? []).map((signal) => `${signal.rank}. *${signal.ticker}* — ${signal.action} | ref. ${brl(signal.ref_price)}`);
        await sendText(`📊 *Sinais de ${signalDate}*\n${lines.join("\n") || "Sem sinais."}`);
      }
    } else if (command === "/posicoes") {
      const { data: latest, error: latestError } = await supabase.from("positions").select("as_of").order("as_of", { ascending: false }).limit(1);
      if (latestError) throw latestError;
      if (!latest?.[0]) {
        await sendText("Ainda não há posições reconciliadas.");
      } else {
        const asOf = latest[0].as_of;
        const { data, error } = await supabase.from("positions").select("ticker,qty,avg_price,stop_price,take_price").eq("as_of", asOf).gt("qty", 0).order("ticker");
        if (error) throw error;
        const lines = (data ?? []).map((position) => `• *${position.ticker}* — ${position.qty} cotas a ${brl(position.avg_price)}`);
        await sendText(`📌 *Posições em ${asOf}*\n${lines.join("\n") || "Nenhuma posição ativa."}`);
      }
    } else if (command === "/carteira" || command === "/performance" || command === "/grafico") {
      const { data, error } = await supabase.from("equity").select("date,equity,cash,pos_value,n_positions").order("date", { ascending: true });
      if (error) throw error;
      const curve = (data ?? []) as EquityPoint[];
      if (!curve.length) {
        await sendText("Ainda não há snapshots de patrimônio.");
      } else if (command === "/carteira") {
        const point = curve.at(-1)!;
        await sendText(["💼 *Carteira em " + point.date + "*", `Patrimônio: *${brl(point.equity)}*`, `Caixa: ${brl(point.cash)}`, `Em posições: ${brl(point.pos_value)}`, `Posições: ${point.n_positions ?? 0}`].join("\n"));
      } else if (command === "/performance") {
        const first = curve[0].equity;
        const last = curve.at(-1)!.equity;
        const returns = ((last / first) - 1) * 100;
        let peak = Number.NEGATIVE_INFINITY;
        let maxDrawdown = 0;
        for (const point of curve) {
          peak = Math.max(peak, point.equity);
          maxDrawdown = Math.min(maxDrawdown, (point.equity / peak - 1) * 100);
        }
        await sendText(["📈 *Performance*", `Início: ${brl(first)}`, `Atual: *${brl(last)}*`, `Retorno: *${pct(returns)}*`, `Max. drawdown: ${pct(maxDrawdown)}`, `Período: ${curve[0].date} a ${curve.at(-1)!.date}`].join("\n"));
      } else if (curve.length < 2) {
        await sendText("São necessários ao menos dois snapshots de patrimônio para gerar o gráfico.");
      } else {
        const form = new FormData();
        form.append("chat_id", String(chatId));
        form.append("caption", "📈 *Curva de patrimônio QuantB3*");
        form.append("parse_mode", "Markdown");
        form.append("document", new Blob([svgChart(curve)], { type: "image/svg+xml" }), "quantb3-performance.svg");
        await telegram(token, "sendDocument", form);
      }
    } else {
      await sendText(`Comando não reconhecido.\n\n${helpText()}`);
    }
    return new Response("ok");
  } catch (error) {
    console.error("telegram-bot error", error instanceof Error ? error.message : error);
    return new Response("internal error", { status: 500 });
  }
});

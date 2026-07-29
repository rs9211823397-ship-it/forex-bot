import { NextResponse } from "next/server";
import { commandBot } from "@/lib/bot/controller";
import { requireUser } from "@/lib/security/session";
import { BotCommand, BotMode } from "@/lib/bot/state";

export const dynamic = "force-dynamic";

const VALID_COMMANDS: BotCommand[] = ["start", "pause", "resume", "stop", "reset"];

export async function POST(req: Request) {
  const auth = await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { command?: BotCommand; mode?: BotMode };
  if (!body.command || !VALID_COMMANDS.includes(body.command)) {
    return NextResponse.json({ error: `command must be one of ${VALID_COMMANDS.join(", ")}` }, { status: 400 });
  }
  const result = await commandBot(body.command, { mode: body.mode, updatedBy: auth.username });
  if (!result.ok) return NextResponse.json({ ok: false, error: result.reason, state: result }, { status: 409 });
  return NextResponse.json({ ok: true, state: result });
}

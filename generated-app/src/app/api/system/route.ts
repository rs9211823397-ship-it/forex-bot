import { NextResponse } from "next/server";
import { getBotState, commandBot } from "@/lib/bot/controller";
import { requireUser } from "@/lib/security/session";
import { BotCommand } from "@/lib/bot/state";

export const dynamic = "force-dynamic";

// BACKWARD-COMPATIBLE shim mapping legacy engine_state to the authoritative
// bot state machine (Feature 1). New clients should use /api/bot/*.
export async function GET() {
  const bot = await getBotState();
  return NextResponse.json({
    state: {
      running: bot.status === "RUNNING",
      paused: bot.status === "PAUSED",
      status: bot.status,
      mode: bot.mode,
      updatedAt: bot.updatedAt,
    },
    bot,
  });
}

export async function POST(req: Request) {
  const auth = await requireUser(req);
  const body = (await req.json()) as {
    action: "start" | "pause" | "stop" | "emergency_close";
    mode?: "paper" | "live";
  };
  const command: BotCommand =
    body.action === "emergency_close" ? "emergency" : body.action;
  const result = await commandBot(command, {
    mode: body.mode,
    updatedBy: auth.username,
    closeOpenPositions: body.action === "emergency_close",
  });
  return NextResponse.json({
    state: {
      running: result.next === "RUNNING",
      paused: result.next === "PAUSED",
      status: result.next,
      mode: body.mode || "paper",
      emergencyClosed: result.closedPositions,
    },
    bot: result,
  });
}

import { NextResponse } from "next/server";
import { getBotSettings, updateBotSettings } from "@/lib/bot/controller";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

export async function GET() {
  const settings = await getBotSettings();
  return NextResponse.json({ settings });
}

export async function PATCH(req: Request) {
  await requireUser(req);
  const patch = (await req.json().catch(() => ({}))) as Record<string, number | boolean>;
  const settings = await updateBotSettings(patch);
  return NextResponse.json({ settings });
}

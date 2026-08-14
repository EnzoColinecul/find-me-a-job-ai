import Image from "next/image";
import { cx } from "./ui/cx";

/** Logo + wordmark. Top-left of the map screens, top of the workspace rail. */
export default function AppMark({
  size = 26,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <div className={cx("flex items-center gap-2", className)}>
      <Image
        src="/logo.png"
        alt=""
        width={size}
        height={size}
        priority
        className="flex-none object-contain"
        style={{ width: size, height: size }}
      />
      <span className="text-[13px] font-bold text-ink">Find Me a Job AI</span>
    </div>
  );
}

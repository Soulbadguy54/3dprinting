import { Emoji, EmojiStyle } from 'emoji-picker-react'

/** Preserve existing Twitter emoji rendering while keeping picker assets
 * out of the first-load JavaScript bundle. */
export default function EmojiDisplay({ unified, size }: { unified: string; size: number }) {
  return <Emoji unified={unified} size={size} emojiStyle={EmojiStyle.TWITTER} />
}

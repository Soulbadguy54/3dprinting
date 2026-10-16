import EmojiPicker, { EmojiStyle, Theme } from 'emoji-picker-react'
import russianEmojis from 'emoji-picker-react/dist/data/emojis-ru'

/** Heavy searchable picker is downloaded only when a user opens the editor. */
export default function EmojiPickerPanel({ onSelect }: { onSelect: (emoji: string) => void }) {
  return (
    <EmojiPicker
      theme={Theme.DARK}
      emojiData={russianEmojis}
      emojiStyle={EmojiStyle.TWITTER}
      width="100%"
      height={340}
      lazyLoadEmojis
      autoFocusSearch={false}
      searchPlaceholder="Поиск эмодзи"
      previewConfig={{ showPreview: false }}
      onEmojiClick={(value) => onSelect(value.emoji)}
    />
  )
}

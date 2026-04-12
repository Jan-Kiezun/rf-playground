interface Props {
  src: string
  caption?: string
}

export default function ImageViewer({ src, caption }: Props) {
  return (
    <div className="bg-gray-800 rounded-xl overflow-hidden border border-gray-700">
      <img src={src} alt={caption ?? 'Satellite image'} className="w-full object-contain max-h-96" />
      {caption && (
        <p className="text-xs text-gray-400 p-2 text-center">{caption}</p>
      )}
    </div>
  )
}

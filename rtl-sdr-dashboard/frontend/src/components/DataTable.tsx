interface Column<T> {
  key: keyof T
  label: string
  render?: (val: T[keyof T], row: T) => React.ReactNode
}

interface Props<T extends object> {
  columns: Column<T>[]
  data: T[]
  emptyMessage?: string
}

export default function DataTable<T extends object>({ columns, data, emptyMessage = 'No data' }: Props<T>) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-gray-500 text-sm">{emptyMessage}</div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-700">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-800">
          <tr>
            {columns.map((col) => (
              <th key={String(col.key)} className="px-4 py-3 text-left text-gray-400 font-medium">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {data.map((row, idx) => (
            <tr key={idx} className="hover:bg-gray-800/50 transition-colors">
              {columns.map((col) => (
                <td key={String(col.key)} className="px-4 py-3 text-gray-300">
                  {col.render ? col.render(row[col.key], row) : String(row[col.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

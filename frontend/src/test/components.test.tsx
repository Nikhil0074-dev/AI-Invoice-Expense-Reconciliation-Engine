import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import LineItemsEditor from '../components/invoice-review/LineItemsEditor'
import { Pagination, ScoreBar, StatusBadge } from '../components/ui'
import Dropzone from '../components/upload/Dropzone'

describe('components', () => {
  it('renders status badges with readable labels', () => {
    render(<StatusBadge status="READY_FOR_RECONCILIATION" />)
    expect(screen.getByText('Ready to reconcile')).toBeInTheDocument()
  })
  it('shows the match score as a percentage', () => {
    render(<ScoreBar score={0.943} />)
    expect(screen.getByText('94%')).toBeInTheDocument()
  })
  it('paginates', () => {
    const onPage = vi.fn()
    render(<Pagination page={1} total={40} size={15} onPage={onPage} />)
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByText('Prev')).toBeDisabled()
    fireEvent.click(screen.getByText('Next')); expect(onPage).toHaveBeenCalledWith(2)
  })
  it('edits, adds and deletes line items', () => {
    const onChange = vi.fn()
    const item = { description: 'Paper', quantity: '10', unit_price: '500', tax_amount: null, line_total: '5000' }
    render(<LineItemsEditor items={[item]} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Qty line 1'), { target: { value: '12' } })
    expect(onChange).toHaveBeenLastCalledWith([{ ...item, quantity: '12' }])
    fireEvent.click(screen.getByText('+ Add line')); expect(onChange.mock.calls.at(-1)![0]).toHaveLength(2)
    fireEvent.click(screen.getByLabelText('Delete line 1')); expect(onChange).toHaveBeenLastCalledWith([])
  })
  it('read-only line items cannot be edited', () => {
    render(<LineItemsEditor items={[{ description: 'x', quantity: null, unit_price: null, tax_amount: null, line_total: '1' }]} onChange={() => {}} readOnly />)
    expect(screen.getByLabelText('Qty line 1')).toBeDisabled(); expect(screen.queryByText('+ Add line')).toBeNull()
  })
  it('rejects bank CSVs, unsupported types and oversize files before uploading', async () => {
    const uploaded = vi.fn()
    const { container } = render(<Dropzone maxMb={1} onUploaded={uploaded} />)
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    const files = [new File(['a'], 'bank.csv', { type: 'text/csv' }), new File(['a'], 'x.exe', { type: 'application/x-msdownload' }),
      new File([new Uint8Array(2 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' })]
    fireEvent.change(input, { target: { files } })
    await waitFor(() => expect(screen.getByText(/imported on the Transactions page/)).toBeInTheDocument())
    expect(screen.getByText(/Only PDF, JPEG and PNG/)).toBeInTheDocument()
    expect(screen.getByText(/Larger than the 1 MB limit/)).toBeInTheDocument()
    expect(uploaded).not.toHaveBeenCalled()
  })
})

// 錯誤邊界（Iteration 25）
//
// 為什麼需要它：React 的預設行為是「render 期間拋例外就卸載整棵樹」。
// 一張圖表的設定寫錯，整頁會變空白——連旁邊的按鈕都按不動，
// 而畫面上看不出任何線索，只能猜。
//
// 包住每張圖表之後，壞掉的只會是那一塊，其他內容照常運作，
// 而且錯誤訊息會直接顯示在該位置上，不必開 console 也知道哪裡出問題。

import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', this.props.label ?? '', error, info)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div style={{
        padding: '1rem 1.25rem', fontSize: '.85rem', lineHeight: 1.8,
        color: 'var(--red)', background: 'var(--red-soft)',
      }}>
        <strong>{this.props.label ?? '這個區塊'}顯示失敗</strong>
        <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: '.78rem', marginTop: '.3rem' }}>
          {String(error?.message ?? error)}
        </div>
        <div style={{ color: 'var(--dim)', marginTop: '.3rem' }}>
          其餘內容不受影響。
        </div>
      </div>
    )
  }
}

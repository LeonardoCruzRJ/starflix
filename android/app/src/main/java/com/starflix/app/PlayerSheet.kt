package com.starflix.app

import android.graphics.Color
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** 55.3: folha inferior preta do player do celular (sem AlertDialog). Pilha de telas: voltar/← desempilha; toque fora ou voltar na raiz fecha. */
class PlayerSheet(private val root: View, private val tvMode: Boolean = false, private val onVisibility: (Boolean) -> Unit = {}) {
    /** `value` = texto cinza à direita; `selected` != null = botão de opção (laranja quando marcado). */
    class Row(val label: String, val value: String? = null, val selected: Boolean? = null, val sub: String? = null, val toggle: Boolean? = null, val onClick: () -> Unit)

    private class Screen(val title: String, val rows: () -> List<Row>)

    private val panel: View = root.findViewById(R.id.sheetPanel)
    private val back: View = root.findViewById(R.id.sheetBack)
    private val titleView: TextView = root.findViewById(R.id.sheetTitle)
    private val scroll: ScrollView = root.findViewById(R.id.sheetScroll)
    private val list: LinearLayout = root.findViewById(R.id.sheetList)
    private val stack = ArrayList<Screen>()
    private val ctx get() = root.context
    private fun dp(v: Int) = (v * ctx.resources.displayMetrics.density).toInt()

    val isOpen get() = root.visibility == View.VISIBLE

    init {
        root.setOnClickListener { close() }
        back.setOnClickListener { back() }
        if (tvMode) {  // 57.13: na TV a folha é um painel centralizado, navegado pelo controle remoto
            panel.layoutParams = FrameLayout.LayoutParams(dp(640), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_HORIZONTAL or Gravity.BOTTOM).apply { bottomMargin = dp(24) }
        }
    }

    /** Abre a folha numa tela nova (a raiz se estiver fechada; senão empilha como subtela). */
    fun open(title: String, rows: () -> List<Row>) {
        stack.add(Screen(title, rows))
        render()
        if (!isOpen) { root.visibility = View.VISIBLE; onVisibility(true) }
    }

    fun refresh() { if (isOpen) render() }

    fun back() { if (stack.size > 1) { stack.removeAt(stack.size - 1); render() } else close() }

    fun close() {
        if (!isOpen) return
        stack.clear()
        root.visibility = View.GONE
        onVisibility(false)
    }

    private fun render() {
        val s = stack.lastOrNull() ?: return
        titleView.text = s.title
        back.visibility = if (stack.size > 1) View.VISIBLE else View.GONE
        list.removeAllViews()
        val rowsNow = s.rows()
        for (r in rowsNow) list.addView(row(r))
        scroll.scrollTo(0, 0)
        if (tvMode) {  // foco inicial: a opção marcada (ou a primeira)
            val i = rowsNow.indexOfFirst { it.selected == true }.let { if (it < 0) 0 else it }
            list.post { list.getChildAt(i)?.requestFocus() }
        }
        // altura máxima ~60% da tela
        val max = (ctx.resources.displayMetrics.heightPixels * 0.6).toInt() - dp(60)
        scroll.layoutParams = scroll.layoutParams.apply { height = ViewGroup.LayoutParams.WRAP_CONTENT }
        list.measure(View.MeasureSpec.makeMeasureSpec(ctx.resources.displayMetrics.widthPixels, View.MeasureSpec.EXACTLY), View.MeasureSpec.UNSPECIFIED)
        if (list.measuredHeight > max) scroll.layoutParams = scroll.layoutParams.apply { height = max }
    }

    private fun row(r: Row): View {
        val l = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(10), dp(20), dp(10))
            minimumHeight = dp(52)
            isClickable = true
            setOnClickListener { r.onClick() }
            if (tvMode) {
                isFocusable = true
                background = android.graphics.drawable.StateListDrawable().apply {
                    addState(intArrayOf(android.R.attr.state_focused), android.graphics.drawable.GradientDrawable().apply {
                        cornerRadius = dp(10).toFloat(); setColor(Color.parseColor("#33FFFFFF")); setStroke(dp(2), Color.parseColor("#E5A00D"))
                    })
                }
            }
        }
        // texto à esquerda: quebra em várias linhas, nunca corta
        val col = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        col.addView(TextView(ctx).apply {
            text = r.label
            setTextColor(Color.WHITE)
            textSize = if (tvMode) 19f else 16f
        })
        if (!r.sub.isNullOrBlank()) col.addView(TextView(ctx).apply {
            text = r.sub
            setTextColor(Color.parseColor("#B3B3B3"))
            textSize = 13f
        })
        l.addView(col, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (r.value != null) l.addView(TextView(ctx).apply {
            text = r.value
            setTextColor(Color.parseColor("#B3B3B3"))
            textSize = 15f
            gravity = Gravity.END
            maxWidth = (ctx.resources.displayMetrics.widthPixels * 0.4).toInt()
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(12) })
        if (r.toggle != null) l.addView(android.widget.Switch(ctx).apply {
            isChecked = r.toggle
            isClickable = false
            isFocusable = false
            val states = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
            thumbTintList = android.content.res.ColorStateList(states, intArrayOf(Color.parseColor("#E5A00D"), Color.parseColor("#BDBDBD")))
            trackTintList = android.content.res.ColorStateList(states, intArrayOf(Color.parseColor("#66E5A00D"), Color.parseColor("#4DFFFFFF")))
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(12) })
        if (r.selected != null) l.addView(ImageView(ctx).apply {
            setImageResource(if (r.selected) R.drawable.m_radio_on else R.drawable.m_radio_off)
        }, LinearLayout.LayoutParams(dp(24), dp(24)).apply { marginStart = dp(12) })
        return l
    }
}

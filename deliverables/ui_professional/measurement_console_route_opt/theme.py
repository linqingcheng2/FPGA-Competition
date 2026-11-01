"""Restrained, opaque instrument palette; a single scale for native controls."""
BG = '#E9ECEF'
SURFACE = '#FFFFFF'
SIDE = '#F1F3F5'
INK = '#252C34'
MUTED = '#626E79'
BORDER = '#C9CFD5'
BLUE = '#39454F'
PLOT = '#15191E'
GRID = '#303943'
TICK = '#B6BEC7'
TRACE = '#DDE2E6'
GREEN = '#97B9A6'
AMBER = '#D8B57B'
REFERENCE_TRACE = '#EAB46B'
HARDWARE_TRACE = '#70D4C3'


def configure(style, font):
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=INK, font=font)
    for name, color in [('TFrame', BG), ('Surface.TFrame', SURFACE), ('Side.TFrame', SIDE)]:
        style.configure(name, background=color)
    for name, color, fg in [('TLabel', BG, INK), ('Muted.TLabel', BG, MUTED),
                            ('Side.TLabel', SIDE, INK), ('SideMuted.TLabel', SIDE, MUTED),
                            ('Surface.TLabel', SURFACE, INK), ('SurfaceMuted.TLabel', SURFACE, MUTED)]:
        style.configure(name, background=color, foreground=fg)
    style.configure('Badge.TLabel', background=BG, foreground=MUTED, padding=(0, 0))
    style.configure('TLabelframe', background=SIDE, bordercolor=BORDER, borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', background=SIDE, foreground=INK, font=font)
    style.configure('TSeparator', background=BORDER)
    style.configure('TButton', background='#F6F7F8', foreground=INK, padding=(8,4),
                    bordercolor=BORDER, lightcolor='#F6F7F8', darkcolor=BORDER, relief='flat', borderwidth=1)
    style.map('TButton', background=[('active','#E4E8EC'),('pressed','#D7DFE6')], foreground=[('disabled','#919AA3')])
    style.configure('Primary.TButton', background=BLUE, foreground=SURFACE, bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE)
    style.map('Primary.TButton', background=[('disabled','#9EACB8'),('active','#36566F')],foreground=[('disabled','#F9FAFB')])
    style.configure('Stop.TButton', foreground='#913E3E')
    for name in ('TEntry','TCombobox'):
        style.configure(name, fieldbackground=SURFACE, foreground=INK, background=SIDE,
                        bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER, padding=(4,4))
        style.map(name, fieldbackground=[('disabled','#E9ECEF'),('readonly',SURFACE)],
                  foreground=[('disabled','#89939D'),('readonly',INK)],
                  selectbackground=[('readonly',SURFACE)],selectforeground=[('readonly',INK)])
    for name in ('TCheckbutton','TRadiobutton'):
        style.configure(name, background=SIDE, foreground=INK, padding=(0,2), indicatorbackground=SURFACE, indicatorforeground=BLUE)
        style.map(name, background=[('active',SIDE)], foreground=[('disabled','#89939D')])
    style.configure('Chart.TCheckbutton', background=SURFACE)
    style.configure('Reference.TCheckbutton', background=SURFACE, foreground='#9C5700')
    style.configure('Hardware.TCheckbutton', background=SURFACE, foreground='#007C9C')
    style.map('Reference.TCheckbutton',background=[('active',SURFACE)])
    style.map('Hardware.TCheckbutton',background=[('active',SURFACE)])
    style.configure('Reference.TLabel',background=SURFACE,foreground='#9C5700')
    style.configure('Hardware.TLabel',background=SURFACE,foreground='#007C9C')
    style.map('Chart.TCheckbutton',background=[('active',SURFACE)])
    style.configure('TNotebook',background=BG,borderwidth=0)
    style.configure('TNotebook.Tab',padding=(12,6),background='#E2E6EA',foreground=MUTED)
    style.map('TNotebook.Tab',background=[('selected',SURFACE)],foreground=[('selected',INK)])
    style.configure('Horizontal.TProgressbar',background=BLUE,troughcolor='#E0E5EA',bordercolor=SIDE,lightcolor=BLUE,darkcolor=BLUE,thickness=4)
    style.configure('Vertical.TScrollbar',background='#CFD5DB',troughcolor=SIDE,arrowsize=10)
    style.configure('Treeview',background=SURFACE,fieldbackground=SURFACE,foreground=INK,rowheight=29,bordercolor=BORDER)
    style.map('Treeview',background=[('selected','#DFE6EC')],foreground=[('selected',INK)])
    style.configure('Treeview.Heading',background='#EAEDEF',foreground=INK,font=font)
    style.configure('Compare.Treeview',rowheight=27)

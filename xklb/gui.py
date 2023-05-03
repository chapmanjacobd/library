from typing import NoReturn, Tuple

from xklb.utils import log


class UserQuit(BaseException):
    pass


class MrSuperDialogue:
    def __init__(self, path, qty, geom_data=None, true_action="keep", false_action="delete") -> None:
        from tkinter import PhotoImage, Tk
        from tkinter.ttk import Button, Frame, Label, Style

        def raise_error(_self, *_args):
            raise  # pylint: disable=misplaced-bare-raise

        Tk.report_callback_exception = raise_error

        self.root = Tk()
        self.root.title("Library dialogue")
        self.root.wm_attributes("-alpha", 0)

        style = Style(self.root)
        style.theme_use("clam")

        photo = PhotoImage(file="assets/kotobago.png")
        self.root.wm_iconphoto(True, photo)  # noqa: FBT003
        self.root.wm_attributes("-topmost", 1)

        for keyseq in ("<Escape>", "<Control-c>", "<Control-q>"):
            self.root.bind(keyseq, lambda _ev: self.user_quit())

        # menu left
        self.menu_left = Frame(self.root, width=150)
        self.menu_left_upper = Frame(self.menu_left, width=150, height=150)
        self.menu_left_lower = Frame(self.menu_left, width=150)

        true_btn = Button(self.menu_left_upper, text=true_action.title(), command=self.return_true, cursor="heart")
        true_btn.bind("<Return>", lambda _ev: self.return_true())
        true_btn.grid()

        false_btn = Button(
            self.menu_left_lower,
            text=false_action.title(),
            command=self.return_false,
            cursor="spraycan",
        )
        false_btn.bind("<Return>", lambda _ev: self.return_false())
        false_btn.focus()
        false_btn.grid()

        self.menu_left_upper.pack(side="top", fill="both", expand=True)
        self.menu_left_lower.pack(side="top", fill="both", expand=True)

        # title
        self.some_title_frame = Frame(self.root)
        self.some_title = Label(self.some_title_frame, text=f"{true_action.title()} or {false_action.title()}?")
        self.some_title.pack()

        self.message = Label(self.root, text=f"{true_action.title()} {path}?", wraplength=180, justify="center")
        self.message.grid(row=1, column=1)

        # status bar
        self.status_frame = Frame(self.root)
        self.status = Label(self.status_frame, text=f"{qty} media to go")
        self.status.pack(fill="both", expand=True)

        self.menu_left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.some_title_frame.grid(row=0, column=1, sticky="ew")
        self.message.grid(row=1, column=1, sticky="nsew")
        self.status_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        for keyseq in ("y", "2"):
            self.root.bind(keyseq, lambda _ev: self.return_true())
        for keyseq in ("n", "1"):
            self.root.bind(keyseq, lambda _ev: self.return_false())

        if true_action.startswith("d"):
            self.root.bind("<Delete>", lambda _ev: self.return_true())
        if false_action.startswith("d"):
            self.root.bind("<Delete>", lambda _ev: self.return_false())

        # bind first letter key
        self.root.bind(true_action[0], lambda _ev: self.return_true())
        self.root.bind(false_action[0], lambda _ev: self.return_false())

        self.move_window(*(geom_data or []))
        self.root.mainloop()

    def user_quit(self) -> NoReturn:
        raise UserQuit

    def return_true(self) -> None:
        self.action = True
        self.root.destroy()

    def return_false(self) -> None:
        self.action = False
        self.root.destroy()

    def move_window(self, window_width=None, window_height=None, x=None, y=None) -> None:
        s_width = window_width or self.root.winfo_screenwidth()
        s_height = window_height or self.root.winfo_screenheight()

        # window_width, window_height = 380, 150  # override
        x_coordinate = x or 0
        y_coordinate = y or 0
        self.root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")
        self.root.update_idletasks()

        log.info(
            {
                "winfo_root_x": self.root.winfo_x(),
                "winfo_root_y": self.root.winfo_y(),
                "winfo_screen": self.root.winfo_screen(),
                "wm_maxsize": self.root.wm_maxsize(),
            },
        )

        # TODO: Get the screen which contains the Tk Frame
        # current_screen = self.get_monitor_from_coord(self.winfo_x(), self.winfo_y())
        # current_screen.name

        x_coordinate = x_coordinate + int((s_width / 2) - (window_width / 2))
        y_coordinate = y_coordinate + int((s_height / 2) - (window_height / 2))
        self.root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")
        self.root.wm_attributes("-alpha", 1)

    @staticmethod
    def _get_coord_offset_from_monitor(screeninfo_monitor) -> Tuple[int, int]:
        # TODO: assuming screeninfo returns monitors in the same order that Tk is expecting it should
        # be possible to figure out where the monitor sits in the framebuffer then add up the preceding
        # monitors to find the pixel offset within the framebuffer for the window to show up in
        # that monitor but I have some doubts about whether this will work at all as well as
        # the portability of this solution. I cycle through five different monitors throughout
        # the day but I never use more than one simultaneously so I will stop over-optimizing here:
        raise NotImplementedError

    @staticmethod
    def get_monitor_from_coord(coord_x, coord_y):  # noqa: ANN205; -> Monitor
        import screeninfo

        monitors = screeninfo.get_monitors()

        for m in reversed(monitors):
            if m.x <= coord_x <= m.width + m.x and m.y <= coord_y <= m.height + m.y:
                return m
        return monitors[0]


def askkeep(*args, **kwargs):
    return MrSuperDialogue(*args, **kwargs).action


if __name__ == "__main__":
    print(askkeep(r"\\supercali\fragil/istic/expiali//docious.exe", 3))

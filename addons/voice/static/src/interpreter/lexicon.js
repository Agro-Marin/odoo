// @ts-check
/** @odoo-module native */

/** @param {string} phrases */
function wordSet(phrases) {
    return new Set(phrases.split(/\s+/).filter(Boolean));
}

/** @param {string[]} phrases */
function phraseList(phrases) {
    return phrases.map((phrase) => phrase.split(" "));
}

export const FILLER = wordSet(`
    porfa porfavor please ok okay oye hey
`);

export const FILLER_PHRASES = phraseList(["por favor", "de favor", "if you please"]);

export const CONNECTORS = wordSet(`
    y e o u con de del la las el los lo un una unos unas al a en que
    and or with the of an to in on for
`);

export const NEGATIONS = wordSet(`
    no nunca jamas
    not dont don never
`);

export const OPEN_VERBS = wordSet(`
    abre abrir abreme abrime ve ir vamos llevame muestra muestrame mostrar ensename
    open go show launch take
`);

export const SET_VERBS = wordSet(`
    pon ponle poner cambia cambiar cambiale establece asigna asignar escribe
    set change put make write
`);

export const SET_LINKS = wordSet(`
    es son sea igual como a en por
    is to as equals
`);

export const BUTTON_VERBS = wordSet(`
    pulsa presiona oprime aprieta haz clic click ejecuta boton
    press push hit run button
`);

export const DICTATE_VERBS = wordSet(`
    dicta dictar dictame dictado dictate dictation
`);

export const NUMBER_WORDS = wordSet(`
    numero num number
`);

export const COMMAND_WORDS = wordSet(`
    comando command
`);

export const GROUP_BY_TRIGGERS = phraseList([
    "agrupa por",
    "agrupar por",
    "agrupalo por",
    "agrupado por",
    "agrupada por",
    "agrupados por",
    "agrupadas por",
    "agrupa",
    "group by",
    "grouped by",
    "group",
]);

export const INTERVALS = {
    dia: "day",
    dias: "day",
    day: "day",
    days: "day",
    semana: "week",
    semanas: "week",
    week: "week",
    weeks: "week",
    mes: "month",
    meses: "month",
    month: "month",
    months: "month",
    trimestre: "quarter",
    trimestres: "quarter",
    quarter: "quarter",
    quarters: "quarter",
    ano: "year",
    anos: "year",
    year: "year",
    years: "year",
};

/** @type {[string[], string][]} */
export const RELATIVE_PERIODS = [
    [["este", "mes"], "month"],
    [["mes", "actual"], "month"],
    [["this", "month"], "month"],
    [["mes", "pasado"], "month-1"],
    [["mes", "anterior"], "month-1"],
    [["ultimo", "mes"], "month-1"],
    [["last", "month"], "month-1"],
    [["previous", "month"], "month-1"],
    [["este", "ano"], "year"],
    [["ano", "actual"], "year"],
    [["this", "year"], "year"],
    [["ano", "pasado"], "year-1"],
    [["ano", "anterior"], "year-1"],
    [["last", "year"], "year-1"],
    [["previous", "year"], "year-1"],
];

export const MONTHS = {
    enero: 1,
    january: 1,
    febrero: 2,
    february: 2,
    marzo: 3,
    march: 3,
    abril: 4,
    april: 4,
    mayo: 5,
    may: 5,
    junio: 6,
    june: 6,
    julio: 7,
    july: 7,
    agosto: 8,
    august: 8,
    septiembre: 9,
    setiembre: 9,
    september: 9,
    octubre: 10,
    october: 10,
    noviembre: 11,
    november: 11,
    diciembre: 12,
    december: 12,
};

export const VIEW_WORDS = {
    lista: "list",
    list: "list",
    kanban: "kanban",
    tarjetas: "kanban",
    cards: "kanban",
    formulario: "form",
    form: "form",
    calendario: "calendar",
    calendar: "calendar",
    pivote: "pivot",
    pivot: "pivot",
    dinamica: "pivot",
    grafica: "graph",
    grafico: "graph",
    graph: "graph",
    chart: "graph",
    mapa: "map",
    map: "map",
    actividad: "activity",
    actividades: "activity",
    activity: "activity",
    gantt: "gantt",
    cohorte: "cohort",
    cohort: "cohort",
    jerarquia: "hierarchy",
    organigrama: "hierarchy",
    hierarchy: "hierarchy",
};

export const VIEW_TRIGGERS = wordSet(`
    vista view vistas cambia cambiar switch modo mode ver como
`);

export const ORDINALS = {
    primero: 1,
    primera: 1,
    primer: 1,
    first: 1,
    segundo: 2,
    segunda: 2,
    second: 2,
    tercero: 3,
    tercera: 3,
    tercer: 3,
    third: 3,
    cuarto: 4,
    cuarta: 4,
    fourth: 4,
    quinto: 5,
    quinta: 5,
    fifth: 5,
    sexto: 6,
    sexta: 6,
    sixth: 6,
    septimo: 7,
    septima: 7,
    seventh: 7,
    octavo: 8,
    octava: 8,
    eighth: 8,
    noveno: 9,
    novena: 9,
    ninth: 9,
    decimo: 10,
    decima: 10,
    tenth: 10,
};

export const RECORD_NOUNS = wordSet(`
    registro registros linea renglon fila elemento resultado
    record row line item one result
`);

export const TRUE_WORDS = wordSet(
    `si verdadero activado activo marcado yes true on checked`,
);
export const FALSE_WORDS = wordSet(
    `falso desactivado inactivo desmarcado false off unchecked`,
);

export const RELATIVE_DAYS = {
    hoy: 0,
    today: 0,
    manana: 1,
    tomorrow: 1,
    ayer: -1,
    yesterday: -1,
};

/**
 * Whole-sentence commands, each a list of phrasings.
 *
 * @type {Record<string, string[][]>}
 */
export const COMMAND_PHRASES = {
    help: phraseList([
        "ayuda",
        "ayudame",
        "que puedo decir",
        "que digo",
        "comandos",
        "help",
        "what can i say",
        "commands",
    ]),
    open_home: phraseList([
        "inicio",
        "menu principal",
        "menu inicio",
        "pantalla inicio",
        "aplicaciones",
        "todas aplicaciones",
        "home",
        "home menu",
        "home screen",
        "apps",
        "all apps",
    ]),
    back: phraseList([
        "atras",
        "regresa",
        "regresar",
        "volver",
        "vuelve",
        "back",
        "go back",
    ]),
    next: phraseList([
        "siguiente",
        "siguiente registro",
        "proximo",
        "next",
        "next record",
        "next one",
    ]),
    previous: phraseList([
        "anterior",
        "registro anterior",
        "previo",
        "previous",
        "previous record",
        "prev",
    ]),
    new_record: phraseList([
        "nuevo",
        "nueva",
        "nuevo registro",
        "crear",
        "crea",
        "crear nuevo",
        "new",
        "new record",
        "create",
        "create new",
    ]),
    save: phraseList(["guardar", "guarda", "guardalo", "salvar", "save", "save it"]),
    discard: phraseList([
        "descartar",
        "descarta",
        "descartar cambios",
        "deshacer cambios",
        "discard",
        "discard changes",
    ]),
    undo: phraseList(["deshacer", "deshaz", "undo"]),
    show_numbers: phraseList([
        "muestra numeros",
        "mostrar numeros",
        "numeros",
        "numera",
        "show numbers",
        "numbers",
    ]),
    hide_numbers: phraseList([
        "oculta numeros",
        "ocultar numeros",
        "quita numeros",
        "quitar numeros",
        "hide numbers",
        "no numbers",
    ]),
    clear_search: phraseList([
        "quita filtros",
        "quitar filtros",
        "borra filtros",
        "borrar filtros",
        "limpia filtros",
        "limpiar filtros",
        "limpia busqueda",
        "limpiar busqueda",
        "sin filtros",
        "clear search",
        "clear filters",
        "remove filters",
        "no filters",
    ]),
};

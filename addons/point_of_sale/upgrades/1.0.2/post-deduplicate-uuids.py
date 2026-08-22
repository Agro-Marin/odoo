import uuid

from psycopg.types.json import Json


def migrate(cr, version):

    def deduplicate_uuids(table):
        query = f"""
        SELECT UNNEST(ARRAY_AGG(id))
          FROM {table}
         WHERE uuid IS NOT NULL
         GROUP BY uuid
        HAVING COUNT(*) > 1
        """
        while True:
            cr.execute(query)
            if not cr.rowcount:
                break
            ids = [r[0] for r in cr.fetchmany(10000)]
            cr.execute(
                f"UPDATE {table} SET uuid = (%s::json)->>(id::text) WHERE id = ANY(%s)",
                [Json({id_: str(uuid.uuid4()) for id_ in ids}), ids],
            )

    deduplicate_uuids("pos_order")
    deduplicate_uuids("pos_order_line")
    deduplicate_uuids("pos_payment")
